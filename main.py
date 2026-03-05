
# -*- coding: utf-8 -*-
"""
Script principal (Python 3.x) para cargar una cadena pickle desde un archivo
con escapes (\\x80\\x04...) y mostrar/guardar el resultado.
"""
from __future__ import annotations
import sys
from utils.pickle_tools import (
    cargar_pickle_desde_texto,
    guardar_pretty,
    convertir_a_json,
)

def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else 'cadenas/ejemplo.txt'
    obj = cargar_pickle_desde_texto(ruta)

    print("Objeto deserializado:")
    print(obj)

    # Guardados útiles
    guardar_pretty(obj, 'salida_pretty.txt')
    convertir_a_json(obj, 'salida.json')
    print('\nArchivos generados: salida_pretty.txt, salida.json')

if __name__ == '__main__':
    main()
