#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Conversor genérico:
- Soporta pickle normal
- Detecta zlib automáticamente
- Convierte bytes a string
- Soporta estructuras complejas
"""

import sys
import pickle
import json
import zlib


# --------------------------------------------------
# Normalización para JSON (muy importante)
# --------------------------------------------------

def normalize(obj):
    if isinstance(obj, dict):
        return {str(normalize(k)): normalize(v) for k, v in obj.items()}

    elif isinstance(obj, (list, tuple, set)):
        return [normalize(x) for x in obj]

    elif isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except:
            return obj.hex()

    elif hasattr(obj, "__dict__"):
        return normalize(obj.__dict__)

    else:
        return obj


# --------------------------------------------------
# Intento de carga
# --------------------------------------------------

def load_pickle(path):
    with open(path, "rb") as f:
        data = f.read()
    print(f"Leídos {len(data)} bytes de {path}"+data[:100].hex())

    # intento directo
    try:
        return pickle.loads(data)
    except:
        pass

    # intento zlib
    try:
        decompressed = zlib.decompress(data)
        return pickle.loads(decompressed)
    except:
        pass

    raise ValueError("No se pudo cargar el pickle (normal ni zlib)")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    # if len(sys.argv) < 2:
    #     print("uso: pickle2json input [output.json]")
    #     sys.exit(1)
    inp = "laboratorio\\tablas\\Dcts"
    out = inp + ".json"
    # inp = sys.argv[1]
    # out = sys.argv[2] if len(sys.argv) > 2 else inp + ".json"

    obj = load_pickle(inp)
    obj = normalize(obj)

    with open(out, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

    print(f"OK → {out}")



if __name__ == "__main__":

    main()