"""
==== Responsabilidad

Este script mide el coste de recorrer completa la tabla Berkeley `historia`
y el coste de realizar lecturas aleatorias sobre un subconjunto de llaves.

==== Flujo

1. Abre la tabla Berkeley en solo lectura.
2. Recorre la tabla completa N veces y toma tiempos de cada pasada.
3. Conserva las llaves encontradas en la primera pasada.
4. Ejecuta M rondas de lecturas aleatorias de X llaves y mide cada ronda.
5. Permite comparar un modo de solo llaves frente a llaves+valores.
6. Permite añadir el coste real de deserialización con unpickle.

==== Diseño

- Se trabaja con llaves y valores en bruto para no contaminar la medicion con
    deserializacion salvo que se pida el modo decoded.
- La primera pasada se informa por separado porque suele incluir calentamiento
  de cache del SO y del motor.
- Las llaves aleatorias se eligen sin reemplazo dentro de cada ronda.
- En modo `keys`, las lecturas aleatorias usan `exists` para no traer el valor.
- En modo `decoded`, el valor sigue el mismo camino zlib+pickle del ERP.
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import random
import statistics
import time
import zlib
from pathlib import Path
from typing import Any

import berkeleydb


DEFAULT_DB_PATH = Path(__file__).with_name("historia")
DEFAULT_JSON_PATH = Path(__file__).with_name("bench_historia_berkeley.json")
DEFAULT_CSV_PATH = Path(__file__).with_name("bench_historia_berkeley.csv")
READ_MODES = ("full", "keys")
DESERIALIZE_MODES = ("raw", "decoded")


def parse_args() -> argparse.Namespace:
    """Construye los argumentos de linea de comandos para la medicion."""
    parser = argparse.ArgumentParser(
        description="Benchmark sencillo de la tabla Berkeley historia."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Ruta del fichero Berkeley. Por defecto usa ./historia.",
    )
    parser.add_argument(
        "--scan-passes",
        type=int,
        default=3,
        help="Numero de recorridos completos de la tabla.",
    )
    parser.add_argument(
        "--random-passes",
        type=int,
        default=3,
        help="Numero de rondas de lecturas aleatorias.",
    )
    parser.add_argument(
        "--random-keys",
        type=int,
        default=1000,
        help="Numero de llaves aleatorias por ronda.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=12345,
        help="Semilla para hacer reproducible la seleccion aleatoria.",
    )
    parser.add_argument(
        "--read-mode",
        choices=READ_MODES,
        default="full",
        help="Modo de lectura: full lee llave+valor; keys intenta medir solo llave.",
    )
    parser.add_argument(
        "--deserialize-mode",
        choices=DESERIALIZE_MODES,
        default="raw",
        help="Modo de deserialización: raw no deserializa; decoded aplica unpickle real.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help="Ruta del resumen JSON a generar.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Ruta del detalle CSV a generar.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Valida que los argumentos numericos tengan sentido para la prueba."""
    if args.scan_passes <= 0:
        raise ValueError("scan-passes debe ser mayor que 0")
    if args.random_passes <= 0:
        raise ValueError("random-passes debe ser mayor que 0")
    if args.random_keys <= 0:
        raise ValueError("random-keys debe ser mayor que 0")
    if args.deserialize_mode == "decoded" and args.read_mode != "full":
        raise ValueError("deserialize-mode=decoded solo tiene sentido con read-mode=full")


def open_db(db_path: Path) -> Any:
    """Abre la tabla Berkeley en modo solo lectura."""
    db = berkeleydb.db.DB()
    db.open(str(db_path), None, berkeleydb.db.DB_BTREE, berkeleydb.db.DB_RDONLY)
    return db


def safe_div(dividend: float, divisor: float) -> float:
    """Evita divisiones por cero en metricas derivadas."""
    if divisor == 0:
        return 0.0
    return dividend / divisor


def compute_percentile(values: list[float], percentile: float) -> float:
    """Calcula un percentil sencillo por interpolacion lineal."""
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


def deserialize_value(value: bytes) -> object:
    """Replica el camino real de unpickle usado en Berkeley dentro del ERP."""
    try:
        raw = zlib.decompress(value)
    except zlib.error:
        raw = value

    try:
        return pickle.loads(raw, encoding="utf-8")
    except (pickle.UnpicklingError, ValueError, EOFError, AttributeError, ImportError, IndexError):
        return pickle.loads(raw, encoding="latin-1")


def record_size(key: bytes, value: bytes, read_mode: str) -> int:
    """Devuelve el tamaño imputado al registro segun el modo de lectura."""
    if read_mode == "keys":
        return len(key)
    return len(key) + len(value)


def full_scan(
    db: Any,
    collect_keys: bool,
    read_mode: str,
    deserialize_mode: str,
) -> tuple[float, int, int, list[bytes]]:
    """Recorre toda la tabla y devuelve tiempo, registros, bytes y llaves."""
    started = time.perf_counter()
    cursor = db.cursor()
    record = cursor.first()
    rows = 0
    total_bytes = 0
    keys: list[bytes] = []

    while record:
        key, value = record
        rows += 1
        total_bytes += record_size(key, value, read_mode)
        if deserialize_mode == "decoded":
            deserialize_value(value)
        if collect_keys:
            keys.append(bytes(key))
        record = cursor.next()

    cursor.close()
    elapsed = time.perf_counter() - started
    return elapsed, rows, total_bytes, keys


def pick_random_keys(keys: list[bytes], amount: int, rng: random.Random) -> list[bytes]:
    """Selecciona llaves aleatorias sin reemplazo dentro de cada ronda."""
    sample_size = min(amount, len(keys))
    indexes = rng.sample(range(len(keys)), sample_size)
    return [keys[index] for index in indexes]


def read_random_value(db: Any, key: bytes, read_mode: str, deserialize_mode: str) -> tuple[bool, int]:
    """Lee una llave puntual y devuelve si hubo hit y los bytes contabilizados."""
    if read_mode == "keys":
        if not db.exists(key):
            return False, 0
        return True, len(key)

    value = db.get(key)
    if value is None:
        return False, 0
    if deserialize_mode == "decoded":
        deserialize_value(value)
    return True, len(key) + len(value)


def random_reads(
    db: Any,
    keys: list[bytes],
    passes: int,
    amount: int,
    seed: int,
    read_mode: str,
    deserialize_mode: str,
) -> list[dict[str, float | int]]:
    """Ejecuta varias rondas de lecturas aleatorias y devuelve sus metricas."""
    rng = random.Random(seed)
    results: list[dict[str, float | int]] = []

    for pass_index in range(1, passes + 1):
        selected = pick_random_keys(keys, amount, rng)
        started = time.perf_counter()
        hits = 0
        total_bytes = 0

        for key in selected:
            found, counted_bytes = read_random_value(db, key, read_mode, deserialize_mode)
            if not found:
                continue
            hits += 1
            total_bytes += counted_bytes

        elapsed = time.perf_counter() - started
        results.append(
            {
                "pass": pass_index,
                "requested": len(selected),
                "hits": hits,
                "bytes": total_bytes,
                "seconds": elapsed,
                "ops_per_second": safe_div(float(hits), elapsed),
                "bytes_per_second": safe_div(float(total_bytes), elapsed),
            }
        )

    return results


def build_scan_details(scan_times: list[float], rows: int, total_bytes: int) -> list[dict[str, float | int]]:
    """Genera el detalle por pasada para recorridos completos."""
    details: list[dict[str, float | int]] = []
    for pass_index, elapsed in enumerate(scan_times, start=1):
        details.append(
            {
                "pass": pass_index,
                "rows": rows,
                "bytes": total_bytes,
                "seconds": elapsed,
                "rows_per_second": safe_div(float(rows), elapsed),
                "bytes_per_second": safe_div(float(total_bytes), elapsed),
            }
        )
    return details


def summarize_times(values: list[float]) -> dict[str, float]:
    """Resume una serie temporal con media, extremos y percentiles."""
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "p50": compute_percentile(values, 0.50),
        "p95": compute_percentile(values, 0.95),
    }


def build_report(args: argparse.Namespace, scan_details: list[dict[str, float | int]], random_results: list[dict[str, float | int]], keys_found: int) -> dict[str, object]:
    """Construye un resumen serializable con configuracion y metricas."""
    scan_times = [float(item["seconds"]) for item in scan_details]
    random_times = [float(item["seconds"]) for item in random_results]
    return {
        "engine": "berkeley",
        "read_mode": args.read_mode,
        "deserialize_mode": args.deserialize_mode,
        "db_path": str(args.db_path),
        "scan_passes": args.scan_passes,
        "random_passes": args.random_passes,
        "random_keys": args.random_keys,
        "seed": args.seed,
        "keys_found": keys_found,
        "scan": {
            "details": scan_details,
            "first_pass_seconds": scan_times[0],
            "following_summary": summarize_times(scan_times[1:]) if len(scan_times) > 1 else None,
        },
        "random": {
            "details": random_results,
            "summary": summarize_times(random_times),
        },
    }


def write_json_report(report: dict[str, object], output_path: Path) -> None:
    """Escribe el resumen completo en JSON legible."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_report(
    scan_details: list[dict[str, float | int]],
    random_results: list[dict[str, float | int]],
    output_path: Path,
    read_mode: str,
    deserialize_mode: str,
) -> None:
    """Escribe un CSV plano con las pasadas secuenciales y aleatorias."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "read_mode",
        "deserialize_mode",
        "section",
        "pass",
        "rows",
        "requested",
        "hits",
        "bytes",
        "seconds",
        "rows_per_second",
        "ops_per_second",
        "bytes_per_second",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in scan_details:
            writer.writerow(
                {
                    "read_mode": read_mode,
                    "deserialize_mode": deserialize_mode,
                    "section": "scan",
                    "pass": item["pass"],
                    "rows": item["rows"],
                    "requested": "",
                    "hits": "",
                    "bytes": item["bytes"],
                    "seconds": item["seconds"],
                    "rows_per_second": item["rows_per_second"],
                    "ops_per_second": "",
                    "bytes_per_second": item["bytes_per_second"],
                }
            )
        for item in random_results:
            writer.writerow(
                {
                    "read_mode": read_mode,
                    "deserialize_mode": deserialize_mode,
                    "section": "random",
                    "pass": item["pass"],
                    "rows": "",
                    "requested": item["requested"],
                    "hits": item["hits"],
                    "bytes": item["bytes"],
                    "seconds": item["seconds"],
                    "rows_per_second": "",
                    "ops_per_second": item["ops_per_second"],
                    "bytes_per_second": item["bytes_per_second"],
                }
            )


def print_scan_summary(scan_details: list[dict[str, float | int]], keys_found: int) -> None:
    """Muestra un resumen legible de los recorridos completos."""
    first = scan_details[0]
    print("Recorridos completos Berkeley")
    print(f"  registros: {first['rows']}")
    print(f"  llaves guardadas: {keys_found}")
    print(f"  bytes leidos por pasada: {first['bytes']}")
    print(f"  primera pasada: {float(first['seconds']):.6f} s")
    print(f"  throughput primera pasada: {float(first['rows_per_second']):.2f} reg/s, {float(first['bytes_per_second']):.2f} B/s")
    if len(scan_details) > 1:
        following = [float(item["seconds"]) for item in scan_details[1:]]
        summary = summarize_times(following)
        print(f"  siguientes pasadas: {[f'{value:.6f}' for value in following]}")
        print(f"  media siguientes: {summary['mean']:.6f} s")
        print(f"  min/max siguientes: {summary['min']:.6f} / {summary['max']:.6f} s")
        print(f"  p50/p95 siguientes: {summary['p50']:.6f} / {summary['p95']:.6f} s")


def print_random_summary(results: list[dict[str, float | int]]) -> None:
    """Muestra el detalle y la media de las rondas aleatorias."""
    print("Lecturas aleatorias Berkeley")
    for result in results:
        print(
            "  ronda {pass}: solicitadas={requested} hits={hits} bytes={bytes} tiempo={seconds:.6f} s ops/s={ops_per_second:.2f} B/s={bytes_per_second:.2f}".format(
                **result
            )
        )

    times = [float(result["seconds"]) for result in results]
    summary = summarize_times(times)
    print(f"  media rondas aleatorias: {summary['mean']:.6f} s")
    print(f"  min/max rondas aleatorias: {summary['min']:.6f} / {summary['max']:.6f} s")
    print(f"  p50/p95 rondas aleatorias: {summary['p50']:.6f} / {summary['p95']:.6f} s")


def main() -> None:
    """Orquesta la medicion completa de recorridos y accesos aleatorios."""
    args = parse_args()
    validate_args(args)

    db = open_db(args.db_path)
    try:
        scan_times: list[float] = []
        rows = 0
        total_bytes = 0
        keys: list[bytes] = []

        for pass_index in range(args.scan_passes):
            elapsed, rows, total_bytes, pass_keys = full_scan(
                db,
                collect_keys=pass_index == 0,
                read_mode=args.read_mode,
                deserialize_mode=args.deserialize_mode,
            )
            scan_times.append(elapsed)
            if pass_index == 0:
                keys = pass_keys

        print(f"Modo de lectura Berkeley: {args.read_mode}")
        print(f"Modo de deserialización Berkeley: {args.deserialize_mode}")
        scan_details = build_scan_details(scan_times, rows, total_bytes)
        print_scan_summary(scan_details, len(keys))
        random_results = random_reads(
            db=db,
            keys=keys,
            passes=args.random_passes,
            amount=args.random_keys,
            seed=args.seed,
            read_mode=args.read_mode,
            deserialize_mode=args.deserialize_mode,
        )
        print_random_summary(random_results)
        report = build_report(args, scan_details, random_results, len(keys))
        write_json_report(report, args.output_json)
        write_csv_report(scan_details, random_results, args.output_csv, args.read_mode, args.deserialize_mode)
        print(f"JSON generado en: {args.output_json}")
        print(f"CSV generado en: {args.output_csv}")
    finally:
        db.close()


if __name__ == "__main__":
    main()