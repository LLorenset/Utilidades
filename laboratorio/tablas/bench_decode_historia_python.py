"""
==== Responsabilidad

Este script compara en Python la velocidad de deserialización de los values
exportados a fichero plano: Berkeley con zlib+pickle, la variante msgpack y
payloads bincodec usando el módulo real worker_python/bincodec.py. También puede
medir variantes proyectadas de bincodec cuando el orden y el tipo de algunos
campos ya son conocidos, así como una extensión CPython en C cuando está
disponible en el directorio del benchmark.

==== Flujo

1. Carga en memoria tres ficheros planos con framing [len][payload].
2. Ejecuta varias pasadas secuenciales de decode completo para cada formato.
3. Ejecuta rondas aleatorias sobre subconjuntos de registros.
4. Escribe un JSON y un CSV con detalle por motor y comparativa resumida.

==== Diseño

- La lectura del fichero se hace una sola vez al inicio para aislar CPU de decode.
- Pickle usa el mismo camino real del ERP: intento zlib y luego pickle.
- Msgpack se genera a partir del dato ya deserializado desde Berkeley para
    comparar el coste puro de unpack frente a pickle y bincodec.
- Bincodec usa funciones del módulo real worker_python/bincodec.py; para soportar
  payloads Pebble sin schema, el benchmark recorre el payload campo a campo,
  avanzando TAG_SKIP y delegando el parseo real en sus funciones privadas.
- Las variantes proyectadas de bincodec usan decode_at con posiciones y tipos
    concretos para simular el caso en el que el servidor ya conoce el esquema y
    solo necesita un subconjunto de columnas.
- Si existe el módulo `fastbincodec`, se mide como motor adicional de decode
    completo para cuantificar cuánto recupera el camino en C frente a Python puro.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import msgpack
import pickle
import random
import statistics
import struct
import sys
import time
import types
import zlib
from pathlib import Path
from typing import Any, Callable


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR.parents[2]
DEFAULT_PICKLE_FILE = BASE_DIR / "historia_berkeley_values.flatbin"
DEFAULT_MSGPACK_FILE = BASE_DIR / "historia_berkeley_msgpack.flatbin"
DEFAULT_BINCODEC_FILE = BASE_DIR / "historia_pebble_payloads.flatbin"
DEFAULT_BINCODEC_MODULE = WORKSPACE_DIR / "testaserver-websocket-GO" / "worker_python" / "bincodec.py"
DEFAULT_OUTPUT_JSON = BASE_DIR / "bench_decode_historia_python.json"
DEFAULT_OUTPUT_CSV = BASE_DIR / "bench_decode_historia_python.csv"
DEFAULT_RANDOM_KEYS = (1000, 10000, 50000)
DEFAULT_BINCODEC_PROJECTIONS: tuple[str, ...] = ()
SUPPORTED_BINCODEC_PROJECTIONS = ("hi_scalar6",)


def parse_args() -> argparse.Namespace:
    """Construye los argumentos del benchmark de decode sobre ficheros planos."""
    parser = argparse.ArgumentParser(description="Compara decode Python de pickle y bincodec sobre ficheros planos.")
    parser.add_argument("--pickle-file", type=Path, default=DEFAULT_PICKLE_FILE, help="Fichero plano con values Berkeley.")
    parser.add_argument("--msgpack-file", type=Path, default=DEFAULT_MSGPACK_FILE, help="Fichero plano con values Berkeley reserializados a msgpack.")
    parser.add_argument("--bincodec-file", type=Path, default=DEFAULT_BINCODEC_FILE, help="Fichero plano con payloads bincodec.")
    parser.add_argument("--bincodec-module", type=Path, default=DEFAULT_BINCODEC_MODULE, help="Ruta al módulo worker_python/bincodec.py.")
    parser.add_argument("--scan-passes", type=int, default=3, help="Número de pasadas secuenciales completas.")
    parser.add_argument("--random-passes", type=int, default=5, help="Número de rondas aleatorias por tamaño de muestra.")
    parser.add_argument("--random-keys", nargs="+", type=int, default=list(DEFAULT_RANDOM_KEYS), help="Tamaños de muestra aleatoria.")
    parser.add_argument("--bincodec-projections", nargs="*", default=list(DEFAULT_BINCODEC_PROJECTIONS), choices=SUPPORTED_BINCODEC_PROJECTIONS, help="Perfiles opcionales de decode_at con esquema y proyección parcial.")
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


def load_bincodec_module(module_path: Path) -> types.ModuleType:
    """Carga dinámicamente el módulo real worker_python/bincodec.py."""
    spec = importlib.util.spec_from_file_location("bench_worker_python_bincodec", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"no se pudo cargar el módulo bincodec desde {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_fastbincodec_module() -> types.ModuleType | None:
    """Carga la extensión C local si está disponible junto al benchmark."""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    try:
        return importlib.import_module("fastbincodec")
    except ModuleNotFoundError:
        return None


def decode_pickle_value(payload: bytes) -> object:
    """Replica el camino real de unpickle usado por Berkeley dentro del ERP."""
    try:
        raw = zlib.decompress(payload)
    except zlib.error:
        raw = payload

    try:
        return pickle.loads(raw, encoding="utf-8")
    except (pickle.UnpicklingError, ValueError, EOFError, AttributeError, ImportError, IndexError):
        return pickle.loads(raw, encoding="latin-1")


def decode_bincodec_payload(codec_module: types.ModuleType, payload: bytes) -> list[Any]:
    """Recorre un payload Pebble con el propio bincodec.py soportando TAG_SKIP."""
    values: list[Any] = []
    offset = 0
    while offset < len(payload):
        if payload[offset] == codec_module.TAG_SKIP:
            if offset + 1 >= len(payload):
                raise ValueError(f"bincodec: skip truncado en offset {offset}")
            offset += 2
            continue
        value, offset = codec_module._read_any_field(payload, offset)
        values.append(value)
    return values


def decode_msgpack_value(payload: bytes) -> object:
    """Deserializa un payload msgpack a objetos Python nativos."""
    return msgpack.unpackb(payload, raw=False)


def decode_fastbincodec_payload(codec_module: types.ModuleType, payload: bytes) -> list[Any]:
    """Decodifica un payload completo usando la extensión CPython en C."""
    return codec_module.decode_record(payload)


def build_projection_plan(codec_module: types.ModuleType, profile: str) -> tuple[list[int], list[Any]]:
    """Construye posiciones y FieldDef para un perfil proyectado conocido."""
    if profile != "hi_scalar6":
        raise ValueError(f"perfil bincodec no soportado: {profile}")

    fields = [
        codec_module.FieldDef(name="usuario", type=codec_module.FieldType.STRING),
        codec_module.FieldDef(name="fecha", type=codec_module.FieldType.DATE),
        codec_module.FieldDef(name="hora", type=codec_module.FieldType.STRING),
        codec_module.FieldDef(name="proceso", type=codec_module.FieldType.STRING),
        codec_module.FieldDef(name="documento", type=codec_module.FieldType.STRING),
        codec_module.FieldDef(name="estado", type=codec_module.FieldType.INT),
    ]
    return list(range(len(fields))), fields


def decode_bincodec_projection(codec_module: types.ModuleType, payload: bytes, profile: str) -> list[Any]:
    """Decodifica solo el subconjunto de campos definido por un perfil."""
    positions, fields = build_projection_plan(codec_module, profile)
    return codec_module.decode_at(payload, positions, fields)


def make_bincodec_projection_decoder(codec_module: types.ModuleType, profile: str) -> Callable[[bytes], object]:
    """Precompila el plan de proyección para no contaminar la medición por registro."""
    positions, fields = build_projection_plan(codec_module, profile)

    def decode_payload(payload: bytes) -> list[Any]:
        return codec_module.decode_at(payload, positions, fields)

    return decode_payload


def build_scan_details(scan_times: list[float], rows: int, total_bytes: int) -> list[dict[str, float | int]]:
    """Construye el detalle por pasada de las secuencias completas."""
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


def pick_random_records(records: list[bytes], amount: int, rng: random.Random) -> list[bytes]:
    """Selecciona registros aleatorios sin reemplazo dentro de una ronda."""
    sample_size = min(amount, len(records))
    indexes = rng.sample(range(len(records)), sample_size)
    return [records[index] for index in indexes]


def run_full_scan(records: list[bytes], decode_func: Callable[[bytes], object]) -> tuple[float, int, int]:
    """Ejecuta una pasada secuencial completa de decode sobre todos los registros."""
    started = time.perf_counter()
    total_bytes = 0
    for payload in records:
        decode_func(payload)
        total_bytes += len(payload)
    elapsed = time.perf_counter() - started
    return elapsed, len(records), total_bytes


def run_random_reads(
    records: list[bytes],
    decode_func: Callable[[bytes], object],
    random_keys: int,
    passes: int,
    seed: int,
) -> list[dict[str, float | int]]:
    """Ejecuta rondas aleatorias de decode sobre registros ya cargados en memoria."""
    rng = random.Random(seed)
    results: list[dict[str, float | int]] = []

    for pass_index in range(1, passes + 1):
        selected = pick_random_records(records, random_keys, rng)
        started = time.perf_counter()
        total_bytes = 0
        for payload in selected:
            decode_func(payload)
            total_bytes += len(payload)
        elapsed = time.perf_counter() - started
        results.append(
            {
                "pass": pass_index,
                "requested": len(selected),
                "hits": len(selected),
                "bytes": total_bytes,
                "seconds": elapsed,
                "ops_per_second": safe_div(float(len(selected)), elapsed),
                "bytes_per_second": safe_div(float(total_bytes), elapsed),
            }
        )
    return results


def benchmark_decoder(
    engine: str,
    file_path: Path,
    records: list[bytes],
    flat_bytes: int,
    decode_func: Callable[[bytes], object],
    args: argparse.Namespace,
) -> dict[str, object]:
    """Mide un motor de decode sobre su fichero plano ya cargado en memoria."""
    scan_times: list[float] = []
    rows = 0
    total_payload_bytes = 0
    for _ in range(args.scan_passes):
        elapsed, rows, total_payload_bytes = run_full_scan(records, decode_func)
        scan_times.append(elapsed)

    random_reports: list[dict[str, object]] = []
    for random_keys in args.random_keys:
        details = run_random_reads(records, decode_func, random_keys, args.random_passes, args.seed + random_keys)
        random_times = [float(item["seconds"]) for item in details]
        random_reports.append(
            {
                "random_keys": random_keys,
                "details": details,
                "summary": summarize_times(random_times),
            }
        )

    scan_details = build_scan_details(scan_times, rows, total_payload_bytes)
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


def find_random_summary(report: dict[str, object], random_keys: int) -> dict[str, float]:
    """Localiza el resumen aleatorio de un tamaño de muestra concreto."""
    for item in report["random"]:
        if int(item["random_keys"]) == random_keys:
            return item["summary"]
    raise KeyError(f"no existe random_keys={random_keys}")


def gain_pct(reference: float, candidate: float) -> float:
    """Devuelve ganancia porcentual positiva cuando candidate es más rápido."""
    if reference == 0:
        return 0.0
    return ((reference - candidate) / reference) * 100.0


def build_metric_comparison(pickle_seconds: float | None, msgpack_seconds: float | None, bincodec_seconds: float | None) -> dict[str, float | None]:
    """Construye una comparación homogénea entre pickle, msgpack y bincodec."""
    return {
        "pickle_seconds": pickle_seconds,
        "msgpack_seconds": msgpack_seconds,
        "bincodec_seconds": bincodec_seconds,
        "msgpack_vs_pickle_gain_pct": gain_pct(pickle_seconds, msgpack_seconds) if pickle_seconds is not None and msgpack_seconds is not None else None,
        "bincodec_vs_pickle_gain_pct": gain_pct(pickle_seconds, bincodec_seconds) if pickle_seconds is not None and bincodec_seconds is not None else None,
        "bincodec_vs_msgpack_gain_pct": gain_pct(msgpack_seconds, bincodec_seconds) if msgpack_seconds is not None and bincodec_seconds is not None else None,
    }


def build_comparisons(
    pickle_report: dict[str, object],
    msgpack_report: dict[str, object],
    bincodec_report: dict[str, object],
    random_keys: list[int],
) -> list[dict[str, object]]:
    """Construye la comparativa porcentual entre pickle, msgpack y bincodec."""
    comparisons: list[dict[str, object]] = []
    pickle_scan_first = float(pickle_report["scan"]["first_pass_seconds"])
    msgpack_scan_first = float(msgpack_report["scan"]["first_pass_seconds"])
    bincodec_scan_first = float(bincodec_report["scan"]["first_pass_seconds"])
    pickle_following = pickle_report["scan"]["following_summary"]
    msgpack_following = msgpack_report["scan"]["following_summary"]
    bincodec_following = bincodec_report["scan"]["following_summary"]

    for amount in random_keys:
        pickle_random = find_random_summary(pickle_report, amount)
        msgpack_random = find_random_summary(msgpack_report, amount)
        bincodec_random = find_random_summary(bincodec_report, amount)
        comparisons.append(
            {
                "random_keys": amount,
                "scan_first": build_metric_comparison(pickle_scan_first, msgpack_scan_first, bincodec_scan_first),
                "scan_following": build_metric_comparison(
                    float(pickle_following["mean"]) if pickle_following else None,
                    float(msgpack_following["mean"]) if msgpack_following else None,
                    float(bincodec_following["mean"]) if bincodec_following else None,
                ),
                "random_mean": build_metric_comparison(
                    float(pickle_random["mean"]),
                    float(msgpack_random["mean"]),
                    float(bincodec_random["mean"]),
                ),
            }
        )
    return comparisons


def build_projection_comparisons(
    pickle_report: dict[str, object],
    msgpack_report: dict[str, object],
    bincodec_report: dict[str, object],
    projection_reports: list[dict[str, object]],
    random_keys: list[int],
) -> list[dict[str, object]]:
    """Resume cuánto recupera cada proyección bincodec frente a los motores base."""
    comparisons: list[dict[str, object]] = []
    pickle_scan_first = float(pickle_report["scan"]["first_pass_seconds"])
    msgpack_scan_first = float(msgpack_report["scan"]["first_pass_seconds"])
    bincodec_scan_first = float(bincodec_report["scan"]["first_pass_seconds"])

    for projection_report in projection_reports:
        projected_scan_first = float(projection_report["scan"]["first_pass_seconds"])
        for amount in random_keys:
            pickle_random = find_random_summary(pickle_report, amount)
            msgpack_random = find_random_summary(msgpack_report, amount)
            bincodec_random = find_random_summary(bincodec_report, amount)
            projection_random = find_random_summary(projection_report, amount)
            comparisons.append(
                {
                    "engine": projection_report["engine"],
                    "random_keys": amount,
                    "scan_first": {
                        "projected_seconds": projected_scan_first,
                        "projected_vs_pickle_gain_pct": gain_pct(pickle_scan_first, projected_scan_first),
                        "projected_vs_msgpack_gain_pct": gain_pct(msgpack_scan_first, projected_scan_first),
                        "projected_vs_bincodec_gain_pct": gain_pct(bincodec_scan_first, projected_scan_first),
                    },
                    "random_mean": {
                        "projected_seconds": float(projection_random["mean"]),
                        "projected_vs_pickle_gain_pct": gain_pct(float(pickle_random["mean"]), float(projection_random["mean"])),
                        "projected_vs_msgpack_gain_pct": gain_pct(float(msgpack_random["mean"]), float(projection_random["mean"])),
                        "projected_vs_bincodec_gain_pct": gain_pct(float(bincodec_random["mean"]), float(projection_random["mean"])),
                    },
                }
            )
    return comparisons


def build_extra_engine_comparisons(
    pickle_report: dict[str, object],
    msgpack_report: dict[str, object],
    bincodec_report: dict[str, object],
    extra_reports: list[dict[str, object]],
    random_keys: list[int],
) -> list[dict[str, object]]:
    """Resume motores adicionales frente a pickle, msgpack y bincodec Python."""
    comparisons: list[dict[str, object]] = []
    pickle_scan_first = float(pickle_report["scan"]["first_pass_seconds"])
    msgpack_scan_first = float(msgpack_report["scan"]["first_pass_seconds"])
    bincodec_scan_first = float(bincodec_report["scan"]["first_pass_seconds"])

    for extra_report in extra_reports:
        extra_scan_first = float(extra_report["scan"]["first_pass_seconds"])
        for amount in random_keys:
            pickle_random = find_random_summary(pickle_report, amount)
            msgpack_random = find_random_summary(msgpack_report, amount)
            bincodec_random = find_random_summary(bincodec_report, amount)
            extra_random = find_random_summary(extra_report, amount)
            comparisons.append(
                {
                    "engine": extra_report["engine"],
                    "random_keys": amount,
                    "scan_first": {
                        "engine_seconds": extra_scan_first,
                        "engine_vs_pickle_gain_pct": gain_pct(pickle_scan_first, extra_scan_first),
                        "engine_vs_msgpack_gain_pct": gain_pct(msgpack_scan_first, extra_scan_first),
                        "engine_vs_bincodec_gain_pct": gain_pct(bincodec_scan_first, extra_scan_first),
                    },
                    "random_mean": {
                        "engine_seconds": float(extra_random["mean"]),
                        "engine_vs_pickle_gain_pct": gain_pct(float(pickle_random["mean"]), float(extra_random["mean"])),
                        "engine_vs_msgpack_gain_pct": gain_pct(float(msgpack_random["mean"]), float(extra_random["mean"])),
                        "engine_vs_bincodec_gain_pct": gain_pct(float(bincodec_random["mean"]), float(extra_random["mean"])),
                    },
                }
            )
    return comparisons


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
                "random_ops_per_second",
                "random_bytes_per_second",
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
                        "random_ops_per_second": first_random["ops_per_second"],
                        "random_bytes_per_second": first_random["bytes_per_second"],
                    }
                )


def print_summary(report: dict[str, object]) -> None:
    """Imprime un resumen compacto de la comparación."""
    print("Resumen decode Python sobre ficheros planos")
    for engine_report in report["engines"]:
        print(
            f"  {engine_report['engine']} registros={engine_report['records']} "
            f"scan_first={engine_report['scan']['first_pass_seconds']:.6f}s"
        )
    print("Comparativa msgpack y bincodec frente a pickle")
    for item in report["comparisons"]:
        print(
            f"  random_keys={item['random_keys']} "
            f"msgpack_scan_gain={item['scan_first']['msgpack_vs_pickle_gain_pct']:.2f}% "
            f"scan_first_gain={item['scan_first']['bincodec_vs_pickle_gain_pct']:.2f}% "
            f"msgpack_random_gain={item['random_mean']['msgpack_vs_pickle_gain_pct']:.2f}% "
            f"random_gain={item['random_mean']['bincodec_vs_pickle_gain_pct']:.2f}%"
        )
    for item in report.get("projection_comparisons", []):
        print(
            f"  {item['engine']} random_keys={item['random_keys']} "
            f"scan_vs_msgpack={item['scan_first']['projected_vs_msgpack_gain_pct']:.2f}% "
            f"scan_vs_bincodec={item['scan_first']['projected_vs_bincodec_gain_pct']:.2f}% "
            f"random_vs_msgpack={item['random_mean']['projected_vs_msgpack_gain_pct']:.2f}% "
            f"random_vs_bincodec={item['random_mean']['projected_vs_bincodec_gain_pct']:.2f}%"
        )
    for item in report.get("extra_engine_comparisons", []):
        print(
            f"  {item['engine']} random_keys={item['random_keys']} "
            f"scan_vs_msgpack={item['scan_first']['engine_vs_msgpack_gain_pct']:.2f}% "
            f"scan_vs_bincodec={item['scan_first']['engine_vs_bincodec_gain_pct']:.2f}% "
            f"random_vs_msgpack={item['random_mean']['engine_vs_msgpack_gain_pct']:.2f}% "
            f"random_vs_bincodec={item['random_mean']['engine_vs_bincodec_gain_pct']:.2f}%"
        )


def main() -> None:
    """Orquesta la carga de ficheros planos y la comparativa de decode."""
    args = parse_args()
    validate_args(args)

    pickle_records, pickle_flat_bytes = load_flat_records(args.pickle_file)
    msgpack_records, msgpack_flat_bytes = load_flat_records(args.msgpack_file)
    bincodec_records, bincodec_flat_bytes = load_flat_records(args.bincodec_file)
    codec_module = load_bincodec_module(args.bincodec_module)
    fastbincodec_module = load_fastbincodec_module()

    pickle_report = benchmark_decoder("pickle-python", args.pickle_file, pickle_records, pickle_flat_bytes, decode_pickle_value, args)
    msgpack_report = benchmark_decoder("msgpack-python", args.msgpack_file, msgpack_records, msgpack_flat_bytes, decode_msgpack_value, args)
    bincodec_report = benchmark_decoder(
        "bincodec-python",
        args.bincodec_file,
        bincodec_records,
        bincodec_flat_bytes,
        lambda payload: decode_bincodec_payload(codec_module, payload),
        args,
    )
    projection_reports: list[dict[str, object]] = []
    for profile in args.bincodec_projections:
        projection_reports.append(
            benchmark_decoder(
                f"bincodec-python-{profile}",
                args.bincodec_file,
                bincodec_records,
                bincodec_flat_bytes,
                make_bincodec_projection_decoder(codec_module, profile),
                args,
            )
        )
    extra_engine_reports: list[dict[str, object]] = []
    if fastbincodec_module is not None:
        extra_engine_reports.append(
            benchmark_decoder(
                "fastbincodec-c",
                args.bincodec_file,
                bincodec_records,
                bincodec_flat_bytes,
                lambda payload: decode_fastbincodec_payload(fastbincodec_module, payload),
                args,
            )
        )
    engine_reports = [pickle_report, msgpack_report, bincodec_report, *projection_reports, *extra_engine_reports]
    report = {
        "config": {
            "pickle_file": str(args.pickle_file),
            "msgpack_file": str(args.msgpack_file),
            "bincodec_file": str(args.bincodec_file),
            "bincodec_module": str(args.bincodec_module),
            "fastbincodec_available": fastbincodec_module is not None,
            "bincodec_projections": args.bincodec_projections,
            "scan_passes": args.scan_passes,
            "random_passes": args.random_passes,
            "random_keys": args.random_keys,
            "seed": args.seed,
        },
        "engines": engine_reports,
        "comparisons": build_comparisons(pickle_report, msgpack_report, bincodec_report, args.random_keys),
        "projection_comparisons": build_projection_comparisons(
            pickle_report,
            msgpack_report,
            bincodec_report,
            projection_reports,
            args.random_keys,
        ),
        "extra_engine_comparisons": build_extra_engine_comparisons(
            pickle_report,
            msgpack_report,
            bincodec_report,
            extra_engine_reports,
            args.random_keys,
        ),
    }
    write_json_report(report, args.output_json)
    write_csv_report(report, args.output_csv)
    print_summary(report)
    print(f"JSON generado en: {args.output_json}")
    print(f"CSV generado en: {args.output_csv}")


if __name__ == "__main__":
    main()