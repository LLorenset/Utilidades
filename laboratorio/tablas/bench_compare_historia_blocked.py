"""
==== Responsabilidad

Este lanzador ejecuta una bateria comparativa con orden bloqueado por dataset,
para reducir la mezcla de caché entre Berkeley, pebbleHIcomp y pebbleHINoComp.

==== Flujo

1. Construye la misma matriz base que el comparador normal.
2. Agrupa las corridas por dataset dentro de cada ronda.
3. Rota el orden de datasets en cada ronda para repartir la ventaja de calentamiento.
4. Consolida resultados con el mismo formato que el comparador normal.

==== Diseño

- El bloqueo se hace por dataset: cada bloque ejecuta todos los tamaños, modos
    y variantes raw/decoded de una misma base antes de pasar a la siguiente.
- La rotacion del orden por ronda evita sesgo fijo de ser siempre primero o ultimo.
- Reutiliza las funciones del comparador existente para no duplicar la logica
  de ejecucion y consolidacion.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import bench_compare_historia as base


def parse_args() -> argparse.Namespace:
    """Construye la configuracion de la bateria bloqueada."""
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Comparador bloqueado por dataset para historia.")
    parser.add_argument("--workdir", type=Path, default=base_dir, help="Directorio de trabajo de los benchmarks.")
    parser.add_argument("--python-script", type=Path, default=base_dir / "bench_historia.py", help="Script Python a lanzar.")
    parser.add_argument("--go-script", type=Path, default=base_dir / "bench_historia.go", help="Script Go a lanzar.")
    parser.add_argument("--python-executable", type=Path, default=Path(__import__("sys").executable), help="Python a usar para el benchmark Berkeley.")
    parser.add_argument("--output-dir", type=Path, default=base_dir / "compare_results_hi_blocked", help="Directorio para resultados individuales y consolidados.")
    parser.add_argument("--berkeley-path", type=Path, default=base_dir / "historia", help="Ruta de la tabla Berkeley historia.")
    parser.add_argument("--pebble-comp-path", type=Path, default=base_dir / "pebbleHIcomp", help="Ruta de la Pebble HI comprimida.")
    parser.add_argument("--pebble-nocomp-path", type=Path, default=base_dir / "pebbleHINoComp", help="Ruta de la Pebble HI sin compresion.")
    parser.add_argument("--scan-passes", type=int, default=2, help="Pasadas secuenciales por corrida.")
    parser.add_argument("--random-passes", type=int, default=9, help="Rondas aleatorias por corrida.")
    parser.add_argument("--random-keys", nargs="+", type=int, default=list(base.DEFAULT_RANDOM_KEYS), help="Lista de tamaños de muestra aleatoria.")
    parser.add_argument("--modes", nargs="+", choices=base.READ_MODES, default=list(base.READ_MODES), help="Modos de lectura a comparar.")
    parser.add_argument("--deserialize-modes", nargs="+", choices=base.DESERIALIZE_MODES, default=list(base.DESERIALIZE_MODES), help="Modos de deserialización a comparar en full.")
    parser.add_argument("--rounds", type=int, default=5, help="Numero de rondas independientes por escenario.")
    parser.add_argument("--seed", type=int, default=12345, help="Semilla base para las corridas.")
    return parser.parse_args()


def rotate_datasets(datasets: list[str], round_index: int) -> list[str]:
    """Rota el orden de datasets para repartir la ventaja del calentamiento."""
    offset = (round_index - 1) % len(datasets)
    return datasets[offset:] + datasets[:offset]


def build_blocked_scenarios(args: argparse.Namespace) -> list[base.Scenario]:
    """Construye escenarios agrupados por dataset dentro de cada ronda."""
    all_scenarios = base.build_scenarios(args)
    grouped: dict[int, dict[str, list[base.Scenario]]] = {}
    datasets = ["berkeley", "pebbleHIcomp", "pebbleHINoComp"]

    for scenario in all_scenarios:
        grouped.setdefault(scenario.round_index, {}).setdefault(scenario.dataset, []).append(scenario)

    ordered: list[base.Scenario] = []
    for round_index in range(1, args.rounds + 1):
        per_round = grouped[round_index]
        for dataset in rotate_datasets(datasets, round_index):
            block = per_round[dataset]
            block.sort(key=lambda item: (item.read_mode, item.deserialize_mode, item.random_keys))
            ordered.extend(block)
    return ordered


def main() -> None:
    """Orquesta la bateria bloqueada y escribe el mismo consolidado base."""
    args = parse_args()
    base.validate_args(args)

    runs_dir = args.output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    scenarios = build_blocked_scenarios(args)

    reports: list[dict[str, object]] = []
    for scenario in scenarios:
        print(
            f"Ejecutando bloqueado dataset={scenario.dataset} motor={scenario.engine} "
            f"modo={scenario.read_mode} random_keys={scenario.random_keys} ronda={scenario.round_index}"
        )
        reports.append(base.run_scenario(args, scenario, runs_dir))

    summary_rows = [base.build_summary_row(report) for report in reports]
    consolidated_rows = base.aggregate_reports(summary_rows)
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
            "ordering": "blocked-by-dataset-rotating",
        },
        "execution_order": [base.scenario_basename(scenario) for scenario in scenarios],
        "runs": summary_rows,
        "aggregated": consolidated_rows,
    }
    base.write_consolidated_json(payload, args.output_dir / "compare_historia.json")
    base.write_consolidated_csv(consolidated_rows, args.output_dir / "compare_historia.csv")
    base.print_consolidated(consolidated_rows)
    print(f"JSON consolidado: {args.output_dir / 'compare_historia.json'}")
    print(f"CSV consolidado: {args.output_dir / 'compare_historia.csv'}")


if __name__ == "__main__":
    main()