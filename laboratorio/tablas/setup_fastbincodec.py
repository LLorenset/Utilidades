"""
===============================================================================
Responsabilidad

Script de build local para compilar la extensión CPython `fastbincodec` dentro
del laboratorio de benchmarks. Está pensado para usar `build_ext --inplace` y
dejar el `.pyd` junto a los scripts de medición.

Diseño

- No toca el módulo principal del servidor.
- Mantiene el experimento aislado en `utilidades/laboratorio/tablas`.
- Fuerza optimización nativa simple (`/O2` o `-O3`) porque el objetivo es medir
  el techo práctico del camino de decode en C.
===============================================================================
"""

from __future__ import annotations

import shutil
import sys
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


def prefer_mingw_on_windows() -> None:
    """Fuerza mingw32 cuando no hay MSVC pero sí gcc disponible."""
    if sys.platform != "win32":
        return
    if "build_ext" not in sys.argv:
        return
    if any(arg.startswith("--compiler=") for arg in sys.argv):
        return
    if shutil.which("cl") is None and shutil.which("gcc") is not None:
        sys.argv.append("--compiler=mingw32")


class BuildExt(build_ext):
    """Ajusta flags de optimización según el compilador real usado."""

    def build_extensions(self) -> None:
        if self.compiler.compiler_type == "msvc":
            compile_args = ["/O2"]
        else:
            compile_args = ["-O3"]

        for extension in self.extensions:
            extension.extra_compile_args = compile_args
        super().build_extensions()


prefer_mingw_on_windows()


setup(
    name="fastbincodec",
    version="0.1.0",
    description="Extensión C mínima para decode completo de registros bincodec.",
    ext_modules=[
        Extension(
            "fastbincodec",
            ["fastbincodec.c"],
        )
    ],
    cmdclass={"build_ext": BuildExt},
)