#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import pickle
import zlib


try:
    from berkeleydb import db
except ImportError:
    from bsddb3 import db


def decode_value(v):
    # intenta pickle directo
    try:
        return pickle.loads(v)
    except:
        pass

    # intenta zlib + pickle
    try:
        return pickle.loads(zlib.decompress(v))
    except:
        pass

    # fallback
    try:
        return v.decode("utf-8")
    except:
        return v.hex()


def normalize(obj):
    if isinstance(obj, dict):
        return {str(k): normalize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [normalize(x) for x in obj]
    elif isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except:
            return obj.hex()
    else:
        return obj


def dump_db(path, out_json):
    d = db.DB()
    d.open(path, None, db.DB_BTREE, db.DB_RDONLY)

    result = {}

    cursor = d.cursor()

    rec = cursor.first()
    while rec:
        k, v = rec

        key = k.decode("utf-8", errors="ignore")
        val = decode_value(v)

        result[key] = normalize(val)

        rec = cursor.next()

    cursor.close()
    d.close()

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"OK → {out_json}")


if __name__ == "__main__":
    # if len(sys.argv) < 2:
    #     print("uso: pickle2json input [output.json]")
    #     sys.exit(1)
    inp = "laboratorio\\tablas\\usGsb"
    out = inp + ".json"
    # inp = sys.argv[1]
    # out = sys.argv[2] if len(sys.argv) > 2 else inp + ".json"
    dump_db(inp, out)

    
    from pathlib import Path

    ruta = "laboratorio\\tablas\\data\\"
    
    rut = Path("laboratorio\\tablas\\data\\")
    for f in rut.iterdir():
        if f.is_file() and not f.suffix :
            print(ruta+f.name)
            dump_db(ruta+f.name, ruta+f.name+".json")




