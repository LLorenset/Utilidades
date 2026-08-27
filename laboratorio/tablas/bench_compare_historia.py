"""
==== Responsabilidad

Este lanzador ejecuta benchmarks comparativos de Berkeley y Pebble sobre la
tabla `historia`, alternando el orden de ejecucion para reducir el sesgo de
cache y consolidando todas las metricas en un solo informe.

==== Flujo

1. Genera una matriz de escenarios por dataset, modo de lectura, deserialización y tamano de muestra.
2. Baraja el orden de ejecucion con una semilla reproducible.
3. Lanza cada benchmark individual y recoge su JSON de salida.
4. Consolida el detalle y resume medias por escenario en JSON y CSV.

==== Diseño

- Los resultados individuales se guardan por corrida para poder inspeccionarlos.
- El consolidado agrega por dataset, modo, deserialización, tamano de muestra y ronda.
- En `keys` solo genera `raw`; en `full` permite `raw` y `decoded`.
- Se usa el mismo script Python actual y el script Go actual, sin duplicar logica.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


READ_MODES = ("full", "keys")
DESERIALIZE_MODES = ("raw", "decoded")
DEFAULT_RANDOM_KEYS = (1000, 10000, 50000)


@dataclass(frozen=True)
class Scenario:
    """Define una corrida concreta de un dataset con un modo y tamaño de muestra."""

    dataset: str
    engine: str
    db_path: str
    read_mode: str
    deserialize_mode: str
    random_keys: int
    round_index: int


def parse_args() -> argparse.Namespace:
    """Construye la configuracion del lanzador comparativo."""
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Comparador consolidado Berkeley vs Pebble para historia.")
    parser.add_argument("--workdir", type=Path, default=base_dir, help="Directorio de trabajo de los benchmarks.")
    parser.add_argument("--python-script", type=Path, default=base_dir / "bench_historia.py", help="Script Python a lanzar.")
    parser.add_argument("--go-script", type=Path, default=base_dir / "bench_historia.go", help="Script Go a lanzar.")
    parser.add_argument("--python-executable", type=Path, default=Path(sys.executable), help="Python a usar para el benchmark Berkeley.")
    parser.add_argument("--output-dir", type=Path, default=base_dir / "compare_results", help="Directorio para resultados individuales y consolidados.")
    parser.add_argument("--berkeley-path", type=Path, default=base_dir / "historia", help="Ruta de la tabla Berkeley historia.")
    parser.add_argument("--pebble-comp-path", type=Path, default=base_dir / "pebbleHIcomp", help="Ruta de la Pebble HI comprimida.")
    parser.add_argument("--pebble-nocomp-path", type=Path, default=base_dir / "pebbleHINoComp", help="Ruta de la Pebble HI sin compresion.")
    parser.add_argument("--scan-passes", type=int, default=2, help="Pasadas secuenciales por corrida.")
    parser.add_argument("--random-passes", type=int, default=9, help="Rondas aleatorias por corrida.")
    parser.add_argument("--random-keys", nargs="+", type=int, default=list(DEFAULT_RANDOM_KEYS), help="Lista de tamaños de muestra aleatoria.")
    parser.add_argument("--modes", nargs="+", choices=READ_MODES, default=list(READ_MODES), help="Modos de lectura a comparar.")
    parser.add_argument("--deserialize-modes", nargs="+", choices=DESERIALIZE_MODES, default=list(DESERIALIZE_MODES), help="Modos de deserialización a comparar en full.")
    parser.add_argument("--rounds", type=int, default=2, help="Numero de rondas independientes por escenario.")
    parser.add_argument("--seed", type=int, default=12345, help="Semilla reproducible para barajar el orden.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Valida que el lanzador reciba una configuracion util."""
    if args.scan_passes <= 0:
        raise ValueError("scan-passes debe ser mayor que 0")
    if args.random_passes <= 0:
        raise ValueError("random-passes debe ser mayor que 0")
    if args.rounds <= 0:
        raise ValueError("rounds debe ser mayor que 0")
    if not args.random_keys:
        raise ValueError("random-keys no puede estar vacio")
    if not args.deserialize_modes:
        raise ValueError("deserialize-modes no puede estar vacio")
    for amount in args.random_keys:
        if amount <= 0:
            raise ValueError("todos los random-keys deben ser mayores que 0")


def deserialize_modes_for(read_mode: str, configured_modes: list[str]) -> list[str]:
    """Restringe las variantes válidas segun el modo de lectura."""
    if read_mode == "keys":
        return ["raw"]
    return list(configured_modes)


def build_scenarios(args: argparse.Namespace) -> list[Scenario]:
    """Genera la matriz completa de corridas a lanzar."""
    scenarios: list[Scenario] = []
    datasets = [
        ("berkeley", "berkeley", str(args.berkeley_path)),
        ("pebbleHIcomp", "pebble", str(args.pebble_comp_path)),
        ("pebbleHINoComp", "pebble", str(args.pebble_nocomp_path)),
    ]
    for round_index in range(1, args.rounds + 1):
        for read_mode in args.modes:
            for deserialize_mode in deserialize_modes_for(read_mode, args.deserialize_modes):
                for random_keys in args.random_keys:
                    for dataset, engine, db_path in datasets:
                        scenarios.append(Scenario(dataset, engine, db_path, read_mode, deserialize_mode, random_keys, round_index))
    return scenarios


def scenario_basename(scenario: Scenario) -> str:
    """Construye un nombre estable para los archivos de una corrida."""
    return f"{scenario.dataset}_{scenario.read_mode}_{scenario.deserialize_mode}_{scenario.random_keys}_r{scenario.round_index}"


def scenario_command(args: argparse.Namespace, scenario: Scenario, json_path: Path, csv_path: Path) -> list[str]:
    """Construye la linea de comando de una corrida individual."""
    common = [
        "--scan-passes",
        str(args.scan_passes),
        "--random-passes",
        str(args.random_passes),
        "--random-keys",
        str(scenario.random_keys),
        "--read-mode",
        scenario.read_mode,
        "--deserialize-mode",
        scenario.deserialize_mode,
        "--seed",
        str(args.seed + scenario.round_index),
        "--output-json",
        str(json_path),
        "--output-csv",
        str(csv_path),
    ]
    if scenario.engine == "berkeley":
        return [str(args.python_executable), str(args.python_script), "--db-path", scenario.db_path, *common]
    return ["go", "run", str(args.go_script), "--pebble-path", scenario.db_path, *common]


def run_scenario(args: argparse.Namespace, scenario: Scenario, runs_dir: Path) -> dict[str, object]:
    """Ejecuta una corrida individual y devuelve su informe JSON."""
    basename = scenario_basename(scenario)
    json_path = runs_dir / f"{basename}.json"
    csv_path = runs_dir / f"{basename}.csv"
    command = scenario_command(args, scenario, json_path, csv_path)
    completed = subprocess.run(
        command,
        cwd=args.workdir,
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(json_path.read_text(encoding="utf-8"))
    report["dataset"] = scenario.dataset
    report["command"] = command
    report["stdout"] = completed.stdout
    report["stderr"] = completed.stderr
    report["round_index"] = scenario.round_index
    return report


def summarize_values(values: list[float]) -> dict[str, float]:
    """Resume una lista de metricas agregadas entre rondas."""
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
    }


def build_summary_row(report: dict[str, object]) -> dict[str, object]:
    """Extrae el resumen principal de una corrida individual."""
    scan = report["scan"]
    random_part = report["random"]
    following = scan.get("following_summary")
    return {
        "dataset": report["dataset"],
        "engine": report["engine"],
        "read_mode": report["read_mode"],
        "deserialize_mode": report.get("deserialize_mode", "raw"),
        "random_keys": report["random_keys"],
        "round_index": report["round_index"],
        "first_pass_seconds": scan["first_pass_seconds"],
        "following_mean_seconds": following["mean"] if following else None,
        "random_mean_seconds": random_part["summary"]["mean"],
    }


def aggregate_reports(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Agrupa corridas por escenario para obtener medias consolidadas."""
    grouped: dict[tuple[str, str, str, str, int], list[dict[str, object]]] = {}
    for row in summary_rows:
        key = (str(row["dataset"]), str(row["engine"]), str(row["read_mode"]), str(row["deserialize_mode"]), int(row["random_keys"]))
        grouped.setdefault(key, []).append(row)

    consolidated: list[dict[str, object]] = []
    for key, rows in sorted(grouped.items()):
        first_values = [float(row["first_pass_seconds"]) for row in rows]
        random_values = [float(row["random_mean_seconds"]) for row in rows]
        following_values = [float(row["following_mean_seconds"]) for row in rows if row["following_mean_seconds"] is not None]
        item = {
            "dataset": key[0],
            "engine": key[1],
            "read_mode": key[2],
            "deserialize_mode": key[3],
            "random_keys": key[4],
            "rounds": len(rows),
            "first_pass": summarize_values(first_values),
            "random_mean": summarize_values(random_values),
            "following_mean": summarize_values(following_values) if following_values else None,
        }
        consolidated.append(item)
    return consolidated


def write_consolidated_json(payload: dict[str, object], output_path: Path) -> None:
    """Escribe el consolidado completo en JSON legible."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_consolidated_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    """Escribe el resumen consolidado en CSV plano."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "engine",
                "dataset",
                "read_mode",
                "deserialize_mode",
                "random_keys",
                "rounds",
                "first_pass_mean",
                "first_pass_min",
                "first_pass_max",
                "following_mean_mean",
                "following_mean_min",
                "following_mean_max",
                "random_mean_mean",
                "random_mean_min",
                "random_mean_max",
            ],
        )
        writer.writeheader()
        for row in rows:
            following = row["following_mean"]
            writer.writerow(
                {
                    "engine": row["engine"],
                    "dataset": row["dataset"],
                    "read_mode": row["read_mode"],
                    "deserialize_mode": row["deserialize_mode"],
                    "random_keys": row["random_keys"],
                    "rounds": row["rounds"],
                    "first_pass_mean": row["first_pass"]["mean"],
                    "first_pass_min": row["first_pass"]["min"],
                    "first_pass_max": row["first_pass"]["max"],
                    "following_mean_mean": following["mean"] if following else "",
                    "following_mean_min": following["min"] if following else "",
                    "following_mean_max": following["max"] if following else "",
                    "random_mean_mean": row["random_mean"]["mean"],
                    "random_mean_min": row["random_mean"]["min"],
                    "random_mean_max": row["random_mean"]["max"],
                }
            )


def print_consolidated(rows: list[dict[str, object]]) -> None:
    """Imprime un resumen legible de la comparativa consolidada."""
    print("Resumen consolidado")
    for row in rows:
        print(
            f"  {row['dataset']} motor={row['engine']} modo={row['read_mode']} deser={row['deserialize_mode']} random_keys={row['random_keys']} "
            f"first_mean={row['first_pass']['mean']:.6f}s random_mean={row['random_mean']['mean']:.6f}s"
        )


def main() -> None:
    """Orquesta la bateria completa de benchmarks comparativos."""
    args = parse_args()
    validate_args(args)

    runs_dir = args.output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios(args)
    rng = random.Random(args.seed)
    rng.shuffle(scenarios)

    reports: list[dict[str, object]] = []
    for scenario in scenarios:
        print(
            f"Ejecutando {scenario.engine} modo={scenario.read_mode} "
            f"deser={scenario.deserialize_mode} random_keys={scenario.random_keys} ronda={scenario.round_index}"
        )
        reports.append(run_scenario(args, scenario, runs_dir))

    summary_rows = [build_summary_row(report) for report in reports]
    consolidated_rows = aggregate_reports(summary_rows)
    payload = {
        "config": {
            "scan_passes": args.scan_passes,
            "random_passes": args.random_passes,
            "random_keys": args.random_keys,
            "modes": args.modes,
            "deserialize_modes": args.deserialize_modes,
            "rounds": args.rounds,
            "seed": args.seed,
            "datasets": ["berkeley", "pebbleHIcomp", "pebbleHINoComp"],
        },
        "execution_order": [scenario_basename(Scenario(str(row["dataset"]), str(row["engine"]), "", str(row["read_mode"]), str(row["deserialize_mode"]), int(row["random_keys"]), int(row["round_index"]))) for row in summary_rows],
        "runs": summary_rows,
        "aggregated": consolidated_rows,
    }
    write_consolidated_json(payload, args.output_dir / "compare_historia.json")
    write_consolidated_csv(consolidated_rows, args.output_dir / "compare_historia.csv")
    print_consolidated(consolidated_rows)
    print(f"JSON consolidado: {args.output_dir / 'compare_historia.json'}")
    print(f"CSV consolidado: {args.output_dir / 'compare_historia.csv'}")


if __name__ == "__main__":
    main()