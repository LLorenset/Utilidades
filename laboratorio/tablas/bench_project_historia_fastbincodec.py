"""
==== Responsabilidad

Este script mide la proyección cruda de payloads bincodec usando la extensión C
fastbincodec. En lugar de materializar el registro, el camino nativo recorre el
payload, copia solo los spans seleccionados a un buffer interno y devuelve el
tamaño producido.

==== Flujo

1. Carga en memoria el flat file [len uint32 BE][payload].
2. Ejecuta dos perfiles fijos de proyección sobre todos los registros.
3. Repite el benchmark en rondas aleatorias.
4. Escribe JSON y CSV con bytes de entrada y bytes proyectados.

==== Diseño

- Se apoya en las funciones C `project_record_len_select_246` y
  `project_record_len_select_246_list2`.
- El valor devuelto es solo el número de bytes proyectados, pero la copia al
  buffer interno ya se ha ejecutado y por tanto el coste de reserialización sí
  entra en la medición.
- El flat file se lee una sola vez para aislar CPU de parseo y copia.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import random
import statistics
import struct
import sys
import time
from pathlib import Path
from typing import Callable


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_BINCODEC_FILE = BASE_DIR / "historia_pebble_payloads.flatbin"
DEFAULT_OUTPUT_JSON = BASE_DIR / "bench_project_historia_fastbincodec.json"
DEFAULT_OUTPUT_CSV = BASE_DIR / "bench_project_historia_fastbincodec.csv"
DEFAULT_RANDOM_KEYS = (1000, 10000, 50000)


def parse_args() -> argparse.Namespace:
    """Construye los argumentos del benchmark de proyección C."""
    parser = argparse.ArgumentParser(description="Benchmark de proyección C sobre payloads bincodec en flat file.")
    parser.add_argument("--bincodec-file", type=Path, default=DEFAULT_BINCODEC_FILE, help="Fichero plano con payloads bincodec.")
    parser.add_argument("--scan-passes", type=int, default=3, help="Número de pasadas secuenciales completas.")
    parser.add_argument("--random-passes", type=int, default=5, help="Número de rondas aleatorias por tamaño de muestra.")
    parser.add_argument("--random-keys", nargs="+", type=int, default=list(DEFAULT_RANDOM_KEYS), help="Tamaños de muestra aleatoria.")
    parser.add_argument("--seed", type=int, default=12345, help="Semilla reproducible para la selección aleatoria.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Ruta del informe JSON.")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV, help="Ruta del informe CSV.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Valida que la configuración del benchmark sea coherente."""
    if args.scan_passes <= 0:
        raise ValueError("scan-passes debe ser mayor que 0")
    if args.random_passes <= 0:
        raise ValueError("random-passes debe ser mayor que 0")
    if not args.random_keys:
        raise ValueError("random-keys no puede estar vacío")
    for amount in args.random_keys:
        if amount <= 0:
            raise ValueError("todos los random-keys deben ser mayores que 0")


def safe_div(dividend: float, divisor: float) -> float:
    """Evita divisiones por cero en métricas derivadas."""
    if divisor == 0:
        return 0.0
    return dividend / divisor


def compute_percentile(values: list[float], percentile: float) -> float:
    """Calcula un percentil simple por interpolación lineal."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_times(values: list[float]) -> dict[str, float]:
    """Resume una serie temporal con media, extremos y percentiles."""
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "p50": compute_percentile(values, 0.50),
        "p95": compute_percentile(values, 0.95),
    }


def load_flat_records(file_path: Path) -> tuple[list[bytes], int]:
    """Carga un fichero plano [len uint32 BE][payload] a memoria."""
    data = file_path.read_bytes()
    records: list[bytes] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError(f"fichero plano truncado leyendo longitud en offset {offset}")
        length = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        end = offset + length
        if end > len(data):
            raise ValueError(f"fichero plano truncado leyendo payload en offset {offset}")
        records.append(data[offset:end])
        offset = end
    return records, len(data)


def load_fastbincodec_module():
    """Carga la extensión C local si está disponible junto al benchmark."""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    return importlib.import_module("fastbincodec")


def available_engines(module) -> list[tuple[str, Callable[[bytes], int]]]:
    """Devuelve los dos perfiles C que se van a medir."""
    return [
        ("fastbincodec-c-project-select_246", module.project_record_len_select_246),
        ("fastbincodec-c-project-select_246_list2", module.project_record_len_select_246_list2),
    ]


def pick_random_records(records: list[bytes], amount: int, rng: random.Random) -> list[bytes]:
    """Selecciona registros aleatorios sin reemplazo dentro de una ronda."""
    sample_size = min(amount, len(records))
    indexes = rng.sample(range(len(records)), sample_size)
    return [records[index] for index in indexes]


def run_full_scan(records: list[bytes], project_func: Callable[[bytes], int]) -> tuple[float, int, int, int]:
    """Ejecuta una pasada secuencial completa de proyección sobre todos los registros."""
    started = time.perf_counter()
    total_bytes = 0
    produced_bytes = 0
    for payload in records:
        produced_bytes += int(project_func(payload))
        total_bytes += len(payload)
    elapsed = time.perf_counter() - started
    return elapsed, len(records), total_bytes, produced_bytes


def run_random_reads(
    records: list[bytes],
    project_func: Callable[[bytes], int],
    random_keys: int,
    passes: int,
    seed: int,
) -> list[dict[str, float | int]]:
    """Ejecuta rondas aleatorias de proyección sobre registros ya cargados en memoria."""
    rng = random.Random(seed)
    results: list[dict[str, float | int]] = []
    for pass_index in range(1, passes + 1):
        selected = pick_random_records(records, random_keys, rng)
        started = time.perf_counter()
        total_bytes = 0
        produced_bytes = 0
        for payload in selected:
            produced_bytes += int(project_func(payload))
            total_bytes += len(payload)
        elapsed = time.perf_counter() - started
        results.append(
            {
                "pass": pass_index,
                "requested": len(selected),
                "hits": len(selected),
                "bytes": total_bytes,
                "produced_bytes": produced_bytes,
                "seconds": elapsed,
                "ops_per_second": safe_div(float(len(selected)), elapsed),
                "bytes_per_second": safe_div(float(total_bytes), elapsed),
                "produced_bytes_per_second": safe_div(float(produced_bytes), elapsed),
            }
        )
    return results


def benchmark_engine(
    engine: str,
    file_path: Path,
    records: list[bytes],
    flat_bytes: int,
    project_func: Callable[[bytes], int],
    args: argparse.Namespace,
) -> dict[str, object]:
    """Mide un motor C de proyección sobre su fichero plano ya cargado en memoria."""
    scan_times: list[float] = []
    scan_details: list[dict[str, float | int]] = []
    rows = 0
    total_payload_bytes = 0
    produced_bytes = 0
    for pass_index in range(1, args.scan_passes + 1):
        elapsed, rows, total_payload_bytes, produced_bytes = run_full_scan(records, project_func)
        scan_times.append(elapsed)
        scan_details.append(
            {
                "pass": pass_index,
                "rows": rows,
                "bytes": total_payload_bytes,
                "produced_bytes": produced_bytes,
                "seconds": elapsed,
                "rows_per_second": safe_div(float(rows), elapsed),
                "bytes_per_second": safe_div(float(total_payload_bytes), elapsed),
                "produced_bytes_per_second": safe_div(float(produced_bytes), elapsed),
            }
        )

    random_reports: list[dict[str, object]] = []
    for random_keys in args.random_keys:
        details = run_random_reads(records, project_func, random_keys, args.random_passes, args.seed + random_keys)
        random_times = [float(item["seconds"]) for item in details]
        random_reports.append(
            {
                "random_keys": random_keys,
                "details": details,
                "summary": summarize_times(random_times),
            }
        )

    return {
        "engine": engine,
        "file_path": str(file_path),
        "records": len(records),
        "flat_file_bytes": flat_bytes,
        "payload_bytes": total_payload_bytes,
        "scan": {
            "details": scan_details,
            "first_pass_seconds": scan_times[0],
            "following_summary": summarize_times(scan_times[1:]) if len(scan_times) > 1 else None,
        },
        "random": random_reports,
    }


def write_json_report(report: dict[str, object], output_path: Path) -> None:
    """Escribe el informe completo en JSON legible."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_report(report: dict[str, object], output_path: Path) -> None:
    """Escribe un CSV plano con los resúmenes por motor y tamaño aleatorio."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "engine",
                "random_keys",
                "scan_first_seconds",
                "scan_following_mean_seconds",
                "random_mean_seconds",
                "scan_first_rows_per_second",
                "scan_first_bytes_per_second",
                "scan_first_produced_bytes_per_second",
                "random_ops_per_second",
                "random_bytes_per_second",
                "random_produced_bytes_per_second",
            ],
        )
        writer.writeheader()
        for engine_report in report["engines"]:
            scan_first = engine_report["scan"]["details"][0]
            following = engine_report["scan"]["following_summary"]
            for random_report in engine_report["random"]:
                summary = random_report["summary"]
                first_random = random_report["details"][0]
                writer.writerow(
                    {
                        "engine": engine_report["engine"],
                        "random_keys": random_report["random_keys"],
                        "scan_first_seconds": engine_report["scan"]["first_pass_seconds"],
                        "scan_following_mean_seconds": following["mean"] if following else "",
                        "random_mean_seconds": summary["mean"],
                        "scan_first_rows_per_second": scan_first["rows_per_second"],
                        "scan_first_bytes_per_second": scan_first["bytes_per_second"],
                        "scan_first_produced_bytes_per_second": scan_first["produced_bytes_per_second"],
                        "random_ops_per_second": first_random["ops_per_second"],
                        "random_bytes_per_second": first_random["bytes_per_second"],
                        "random_produced_bytes_per_second": first_random["produced_bytes_per_second"],
                    }
                )


def print_summary(report: dict[str, object]) -> None:
    """Imprime un resumen compacto de la proyección C."""
    print("Resumen proyección fastbincodec C sobre flat file bincodec")
    for engine_report in report["engines"]:
        first = engine_report["scan"]["details"][0]
        print(
            f"  {engine_report['engine']} registros={engine_report['records']} "
            f"scan_first={engine_report['scan']['first_pass_seconds']:.6f}s "
            f"produced_bytes={first['produced_bytes']}"
        )
        for random_report in engine_report["random"]:
            print(f"  random_keys={random_report['random_keys']} random_mean={random_report['summary']['mean']:.6f}s")


def main() -> None:
    """Orquesta la carga del flat file y el benchmark C de proyección."""
    args = parse_args()
    validate_args(args)

    records, flat_bytes = load_flat_records(args.bincodec_file)
    fastbincodec_module = load_fastbincodec_module()
    engine_reports = [
        benchmark_engine(name, args.bincodec_file, records, flat_bytes, project_func, args)
        for name, project_func in available_engines(fastbincodec_module)
    ]
    report = {
        "config": {
            "bincodec_file": str(args.bincodec_file),
            "scan_passes": args.scan_passes,
            "random_passes": args.random_passes,
            "random_keys": args.random_keys,
            "seed": args.seed,
        },
        "engines": engine_reports,
    }
    write_json_report(report, args.output_json)
    write_csv_report(report, args.output_csv)
    print_summary(report)
    print(f"JSON generado en: {args.output_json}")
    print(f"CSV generado en: {args.output_csv}")


if __name__ == "__main__":
    main()