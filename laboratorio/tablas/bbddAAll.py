import json
import pickle
import msgpack
import berkeleydb

import zlib

def decode_value(v):
    try:
        return pickle.loads(zlib.decompress(v))
    except:
        pass

    try:
        return pickle.loads(v)
    except:
        pass

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


def leer_berkeley(db_path):
    db = berkeleydb.db.DB()
    db.open(db_path, None, berkeleydb.db.DB_BTREE, berkeleydb.db.DB_RDONLY)

    datos = {}

    cursor = db.cursor()
    record = cursor.first()

    while record:
        k, v = record

        try:
            k = k.decode("utf-8")
        except Exception:
            k = str(k)

        try:
            v = decode_value(v)
        except Exception:
            v = str(v)

        datos[k] = normalize(v)
        record = cursor.next()

    cursor.close()
    db.close()

    return datos


def guardar_json(datos, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def guardar_pickle(datos, path):
    with open(path, "wb") as f:
        pickle.dump(datos, f)


def guardar_msgpack(datos, path):
    with open(path, "wb") as f:
        f.write(msgpack.packb(datos, use_bin_type=True))


def main():
    # if len(sys.argv) < 2:
    #     print("uso: pickle2json input [output.json]")
    #     sys.exit(1)
    # inp = "laboratorio\\tablas\\usGsb"
    # out = inp + ".json"
    # inp = sys.argv[1]
    # out = sys.argv[2] if len(sys.argv) > 2 else inp + ".json"
    
    from pathlib import Path

    ruta = "C:\\copias\\datos\\data4\\"
    
    rut = Path(ruta)
    for f in rut.iterdir():
        if f.is_file() and not f.suffix :
            print(ruta+f.name)
            datos = leer_berkeley(ruta+f.name)

            guardar_json(datos, ruta+f.name+".json")
            guardar_pickle(datos, ruta+f.name+".pkl")
            guardar_msgpack(datos, ruta+f.name+".msgpack")



    # datos = leer_berkeley(inp)

    # guardar_json(datos, inp+".json")
    # guardar_pickle(datos, inp+".pkl")
    # guardar_msgpack(datos, inp+".msgpack")

    # print("Exportado a JSON, Pickle y MsgPack")


if __name__ == "__main__":
    main()