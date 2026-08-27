"""
==== Responsabilidad

Este script analiza un consolidado de benchmarks de `historia` y calcula
diferencias porcentuales directas entre Berkeley, pebbleHIcomp y
pebbleHINoComp.

==== Flujo

1. Carga el JSON consolidado de una corrida comparativa.
2. Indexa los resultados por modo de lectura, deserialización y tamano de muestra.
3. Calcula diferencias porcentuales respecto a Berkeley y entre variantes Pebble.
4. Escribe un resumen legible en JSON y CSV.

==== Diseño

- La metrica principal es `ganancia_pct`, positiva cuando el candidato tarda
  menos que la referencia.
- Se analizan por separado `first_mean` y `random_mean`.
- Raw y decoded se comparan por separado para no mezclar I/O con decode.
- Si falta una combinacion esperada, se omite para no inventar datos.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Construye la configuracion del analizador porcentual."""
    base_dir = Path(__file__).resolve().parent
    default_input = base_dir / "compare_results_hi" / "compare_historia.json"
    parser = argparse.ArgumentParser(description="Analisis porcentual de compare_historia.json")
    parser.add_argument("--input-json", type=Path, default=default_input, help="Consolidado JSON de entrada.")
    parser.add_argument("--output-json", type=Path, default=default_input.with_name("compare_historia_analysis.json"), help="Resumen JSON de salida.")
    parser.add_argument("--output-csv", type=Path, default=default_input.with_name("compare_historia_analysis.csv"), help="Resumen CSV de salida.")
    return parser.parse_args()


def safe_gain(reference: float, candidate: float) -> float:
    """Devuelve ganancia porcentual positiva cuando candidate es mas rapido."""
    if reference == 0:
        return 0.0
    return ((reference - candidate) / reference) * 100.0


def load_rows(input_json: Path) -> list[dict[str, object]]:
    """Carga las filas agregadas del consolidado."""
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    return list(payload["aggregated"])


def index_rows(rows: list[dict[str, object]]) -> dict[tuple[str, str, int, str], dict[str, object]]:
    """Indexa por modo, deserialización, random_keys y dataset para comparar."""
    indexed: dict[tuple[str, str, int, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["read_mode"]), str(row.get("deserialize_mode", "raw")), int(row["random_keys"]), str(row["dataset"]))
        indexed[key] = row
    return indexed


def build_analysis(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Construye el analisis porcentual directo entre datasets."""
    indexed = index_rows(rows)
    modes = sorted({str(row["read_mode"]) for row in rows})
    deserialize_modes = sorted({str(row.get("deserialize_mode", "raw")) for row in rows})
    sizes = sorted({int(row["random_keys"]) for row in rows})
    analysis: list[dict[str, object]] = []

    for mode in modes:
        for deserialize_mode in deserialize_modes:
            for size in sizes:
                berkeley = indexed.get((mode, deserialize_mode, size, "berkeley"))
                no_comp = indexed.get((mode, deserialize_mode, size, "pebbleHINoComp"))
                comp = indexed.get((mode, deserialize_mode, size, "pebbleHIcomp"))
                if not berkeley or not no_comp or not comp:
                    continue

                item = {
                    "read_mode": mode,
                    "deserialize_mode": deserialize_mode,
                    "random_keys": size,
                    "first_mean": {
                        "berkeley_vs_pebbleHINoComp_gain_pct": safe_gain(float(berkeley["first_pass"]["mean"]), float(no_comp["first_pass"]["mean"])),
                        "berkeley_vs_pebbleHIcomp_gain_pct": safe_gain(float(berkeley["first_pass"]["mean"]), float(comp["first_pass"]["mean"])),
                        "pebbleHIcomp_vs_pebbleHINoComp_gain_pct": safe_gain(float(comp["first_pass"]["mean"]), float(no_comp["first_pass"]["mean"])),
                    },
                    "random_mean": {
                        "berkeley_vs_pebbleHINoComp_gain_pct": safe_gain(float(berkeley["random_mean"]["mean"]), float(no_comp["random_mean"]["mean"])),
                        "berkeley_vs_pebbleHIcomp_gain_pct": safe_gain(float(berkeley["random_mean"]["mean"]), float(comp["random_mean"]["mean"])),
                        "pebbleHIcomp_vs_pebbleHINoComp_gain_pct": safe_gain(float(comp["random_mean"]["mean"]), float(no_comp["random_mean"]["mean"])),
                    },
                }
                analysis.append(item)
    return analysis


def write_json(output_json: Path, analysis: list[dict[str, object]], source_json: Path) -> None:
    """Escribe el analisis porcentual en JSON."""
    output_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_json": str(source_json),
        "analysis": analysis,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(output_csv: Path, analysis: list[dict[str, object]]) -> None:
    """Escribe el analisis porcentual en CSV plano."""
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "read_mode",
                "deserialize_mode",
                "random_keys",
                "first_berkeley_vs_pebbleHINoComp_gain_pct",
                "first_berkeley_vs_pebbleHIcomp_gain_pct",
                "first_pebbleHIcomp_vs_pebbleHINoComp_gain_pct",
                "random_berkeley_vs_pebbleHINoComp_gain_pct",
                "random_berkeley_vs_pebbleHIcomp_gain_pct",
                "random_pebbleHIcomp_vs_pebbleHINoComp_gain_pct",
            ],
        )
        writer.writeheader()
        for item in analysis:
            writer.writerow(
                {
                    "read_mode": item["read_mode"],
                    "deserialize_mode": item["deserialize_mode"],
                    "random_keys": item["random_keys"],
                    "first_berkeley_vs_pebbleHINoComp_gain_pct": item["first_mean"]["berkeley_vs_pebbleHINoComp_gain_pct"],
                    "first_berkeley_vs_pebbleHIcomp_gain_pct": item["first_mean"]["berkeley_vs_pebbleHIcomp_gain_pct"],
                    "first_pebbleHIcomp_vs_pebbleHINoComp_gain_pct": item["first_mean"]["pebbleHIcomp_vs_pebbleHINoComp_gain_pct"],
                    "random_berkeley_vs_pebbleHINoComp_gain_pct": item["random_mean"]["berkeley_vs_pebbleHINoComp_gain_pct"],
                    "random_berkeley_vs_pebbleHIcomp_gain_pct": item["random_mean"]["berkeley_vs_pebbleHIcomp_gain_pct"],
                    "random_pebbleHIcomp_vs_pebbleHINoComp_gain_pct": item["random_mean"]["pebbleHIcomp_vs_pebbleHINoComp_gain_pct"],
                }
            )


def print_analysis(analysis: list[dict[str, object]]) -> None:
    """Imprime un resumen compacto del analisis porcentual."""
    print("Analisis porcentual")
    for item in analysis:
        print(
            f"  modo={item['read_mode']} deser={item['deserialize_mode']} random_keys={item['random_keys']} "
            f"first noComp vs Berkeley={item['first_mean']['berkeley_vs_pebbleHINoComp_gain_pct']:.2f}% "
            f"comp vs Berkeley={item['first_mean']['berkeley_vs_pebbleHIcomp_gain_pct']:.2f}% "
            f"random noComp vs Berkeley={item['random_mean']['berkeley_vs_pebbleHINoComp_gain_pct']:.2f}% "
            f"comp vs Berkeley={item['random_mean']['berkeley_vs_pebbleHIcomp_gain_pct']:.2f}%"
        )


def main() -> None:
    """Orquesta la carga, el analisis y la escritura de salidas."""
    args = parse_args()
    rows = load_rows(args.input_json)
    analysis = build_analysis(rows)
    write_json(args.output_json, analysis, args.input_json)
    write_csv(args.output_csv, analysis)
    print_analysis(analysis)
    print(f"JSON analisis: {args.output_json}")
    print(f"CSV analisis: {args.output_csv}")


if __name__ == "__main__":
    main()