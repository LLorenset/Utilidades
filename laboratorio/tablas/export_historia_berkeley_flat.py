"""
==== Responsabilidad

Este script exporta los values crudos de la tabla Berkeley `historia` a un
fichero binario plano con framing por longitud, y además genera una variante
msgpack equivalente, para poder medir después el coste puro de deserialización
sin ruido de acceso a BDB.

==== Flujo

1. Abre la tabla Berkeley en solo lectura.
2. Recorre todos los registros o hasta el límite indicado.
3. Escribe cada value pickle como [len uint32 BE][payload bytes].
4. Decodifica ese value con el camino real zlib+pickle y lo vuelve a emitir en msgpack.
5. Genera un JSON lateral con el resumen de la exportación.

==== Diseño

- El formato plano es deliberadamente simple: uint32 big-endian + payload.
- Se exporta el value tal cual está en Berkeley para preservar el camino real
  zlib+pickle del ERP.
- La variante msgpack normaliza contenedores no soportados directamente por
    msgpack para que la comparación mida unpack, no conversiones posteriores.
- El fichero resultante se carga luego completo en memoria para medir CPU pura.
"""

from __future__ import annotations

import argparse
import json
import pickle
import struct
import zlib
from pathlib import Path
from typing import Any

import berkeleydb
import msgpack


DEFAULT_DB_PATH = Path(__file__).with_name("historia")
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("historia_berkeley_values.flatbin")
DEFAULT_MSGPACK_OUTPUT_PATH = Path(__file__).with_name("historia_berkeley_msgpack.flatbin")


def parse_args() -> argparse.Namespace:
    """Construye los argumentos de línea de comandos para la exportación."""
    parser = argparse.ArgumentParser(description="Exporta values Berkeley de historia a binario plano.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Ruta de la tabla Berkeley historia.")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH, help="Ruta del fichero plano de salida.")
    parser.add_argument("--msgpack-output-path", type=Path, default=DEFAULT_MSGPACK_OUTPUT_PATH, help="Ruta del fichero plano msgpack de salida.")
    parser.add_argument("--meta-json", type=Path, default=None, help="Ruta opcional del JSON resumen.")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de registros a exportar. 0 = sin límite.")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Valida que la exportación tenga una configuración coherente."""
    if args.limit < 0:
        raise ValueError("limit no puede ser negativo")


def open_db(db_path: Path) -> Any:
    """Abre la tabla Berkeley en modo solo lectura."""
    db = berkeleydb.db.DB()
    db.open(str(db_path), None, berkeleydb.db.DB_BTREE, berkeleydb.db.DB_RDONLY)
    return db


def meta_path_for(output_path: Path, explicit_path: Path | None) -> Path:
    """Resuelve la ruta del JSON lateral de metadatos."""
    if explicit_path is not None:
        return explicit_path
    return output_path.with_suffix(output_path.suffix + ".json")


def write_record(handle: Any, payload: bytes) -> None:
    """Escribe un registro framing simple [len uint32 BE][payload]."""
    handle.write(struct.pack(">I", len(payload)))
    handle.write(payload)


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


def normalize_for_msgpack(value: object) -> object:
    """Convierte el árbol Python a un subconjunto soportado por msgpack."""
    if isinstance(value, dict):
        return {str(key): normalize_for_msgpack(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalize_for_msgpack(item) for item in value]
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def build_msgpack_payload(pickle_payload: bytes) -> bytes:
    """Decodifica el value Berkeley y lo reserializa a msgpack equivalente."""
    decoded = decode_pickle_value(pickle_payload)
    normalized = normalize_for_msgpack(decoded)
    return msgpack.packb(normalized, use_bin_type=True)


def export_values(db: Any, output_path: Path, msgpack_output_path: Path, limit: int) -> dict[str, object]:
    """Exporta los values Berkeley a plano pickle y a plano msgpack."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    msgpack_output_path.parent.mkdir(parents=True, exist_ok=True)
    cursor = db.cursor()
    record = cursor.first()
    exported = 0
    pickle_total_bytes = 0
    pickle_min_length: int | None = None
    pickle_max_length = 0
    msgpack_total_bytes = 0
    msgpack_min_length: int | None = None
    msgpack_max_length = 0

    with output_path.open("wb") as pickle_handle, msgpack_output_path.open("wb") as msgpack_handle:
        while record:
            _, value = record
            pickle_payload = bytes(value)
            msgpack_payload = build_msgpack_payload(pickle_payload)

            write_record(pickle_handle, pickle_payload)
            write_record(msgpack_handle, msgpack_payload)

            pickle_length = len(pickle_payload)
            pickle_total_bytes += pickle_length
            pickle_min_length = pickle_length if pickle_min_length is None else min(pickle_min_length, pickle_length)
            pickle_max_length = max(pickle_max_length, pickle_length)

            msgpack_length = len(msgpack_payload)
            msgpack_total_bytes += msgpack_length
            msgpack_min_length = msgpack_length if msgpack_min_length is None else min(msgpack_min_length, msgpack_length)
            msgpack_max_length = max(msgpack_max_length, msgpack_length)

            exported += 1
            if limit and exported >= limit:
                break
            record = cursor.next()

    cursor.close()
    return {
        "engine": "berkeley",
        "source_path": str(output_path.parent / DEFAULT_DB_PATH.name) if output_path.parent == DEFAULT_DB_PATH.parent else str(DEFAULT_DB_PATH),
        "records": exported,
        "pickle_payload_bytes": pickle_total_bytes,
        "pickle_min_payload_bytes": pickle_min_length or 0,
        "pickle_max_payload_bytes": pickle_max_length,
        "pickle_flat_file": str(output_path),
        "msgpack_payload_bytes": msgpack_total_bytes,
        "msgpack_min_payload_bytes": msgpack_min_length or 0,
        "msgpack_max_payload_bytes": msgpack_max_length,
        "msgpack_flat_file": str(msgpack_output_path),
        "limit": limit,
    }


def write_meta(meta: dict[str, object], meta_path: Path) -> None:
    """Escribe el resumen JSON de la exportación."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    """Orquesta la exportación plana de values Berkeley."""
    args = parse_args()
    validate_args(args)
    db = open_db(args.db_path)
    try:
        meta = export_values(db, args.output_path, args.msgpack_output_path, args.limit)
        meta["source_path"] = str(args.db_path)
        meta_path = meta_path_for(args.output_path, args.meta_json)
        write_meta(meta, meta_path)
        print(
            "Exportación Berkeley completada: registros={records} pickle_bytes={pickle_payload_bytes} msgpack_bytes={msgpack_payload_bytes}".format(
                **meta
            )
        )
        print(f"Plano pickle: {args.output_path}")
        print(f"Plano msgpack: {args.msgpack_output_path}")
        print(f"Meta: {meta_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()