
# -*- coding: utf-8 -*-
"""Funciones utilitarias para trabajar con pickles.
Compatibles con Python 3.x.
"""
from __future__ import annotations
import pickle
import json
import codecs
from pprint import pformat
from typing import Any

def cargar_pickle_desde_bytes(cadena_bytes: bytes) -> Any:
    """Carga un objeto pickle desde bytes (b"...")."""
    return pickle.loads(cadena_bytes)

def cargar_pickle_desde_texto(ruta_archivo: str) -> Any:
    """Lee un archivo .txt con una cadena de bytes con escapes y devuelve el objeto Python."""
    with open(ruta_archivo, 'r', encoding='utf-8') as f:
        texto = f.read()
    # Convierte texto "\x80\x04..." → b"\x80\x04..."
    raw = codecs.escape_decode(texto)[0]
    return pickle.loads(raw)

def guardar_pretty(obj: Any, ruta: str = 'salida_pretty.txt') -> None:
    """Guarda cualquier objeto en formato legible (pretty print)."""
    contenido = pformat(obj)
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(contenido)

def _json_default(o: Any):
    """Conversor por defecto para objetos no serializables a JSON."""
    try:
        return str(o)
    except Exception:
        return repr(o)

def convertir_a_json(obj: Any, ruta: str = 'salida.json', indent: int = 2) -> None:
    """Intenta guardar el objeto en JSON. Si hay campos no serializables, los convierte a str."""
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, default=_json_default)
