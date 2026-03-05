
# -*- coding: utf-8 -*-
"""Ejemplo de uso de las utilidades desde scripts/."""
from __future__ import annotations
from os import path
import sys
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

from utils.pickle_tools import cargar_pickle_desde_texto

ruta = path.join(path.dirname(__file__), '..', 'cadenas', 'ejemplo.txt')
obj = cargar_pickle_desde_texto(ruta)

print('Ejemplo cargado desde scripts/:')
print(obj)
