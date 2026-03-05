import time
import tracemalloc
from dataclasses import dataclass

N = 10_000_000  # número de instancias
ACC = 50_000_000  # número de accesos para el test de acceso a atributos


# ----------------------------------------------------
# 1) Definiciones de clase
# ----------------------------------------------------

# Clase normal
class Normal:
    def __init__(self, a, b):
        self.a = a
        self.b = b


# Clase con __slots__
class ConSlots:
    __slots__ = ("a", "b")
    def __init__(self, a, b):
        self.a = a
        self.b = b


# Dataclass con slots
@dataclass(slots=True)
class DCSlots:
    a: int
    b: int


# ----------------------------------------------------
# 2) Funciones de benchmark
# ----------------------------------------------------

def bench_create(cls):
    """Mide tiempo de creación y memoria usada al crear N objetos."""
    tracemalloc.start()
    t0 = time.perf_counter()

    objs = [cls(i, i+1) for i in range(N)]

    t1 = time.perf_counter()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return objs, (t1 - t0), (peak / (1024 * 1024))  # segundos, MB


def bench_access(objs):
    """Mide tiempo de acceso intensivo a atributos."""
    t0 = time.perf_counter()
    total = 0
    for _ in range(ACC):
        o = objs[_ % len(objs)]
        total += o.a  # acceso al atributo
    t1 = time.perf_counter()
    return t1 - t0, total


# ----------------------------------------------------
# 3) Ejecución de benchmarks
# ----------------------------------------------------

print(f"### Benchmark con {N:,} instancias y {ACC:,} accesos ###\n")

# --- Clase normal ---
objs_n, t_crea_n, mem_n = bench_create(Normal)
t_acc_n, _ = bench_access(objs_n)
print(f"[Normal]        Crear: {t_crea_n:0.3f}s   Memoria: {mem_n:0.2f} MB   Accesos: {t_acc_n:0.3f}s")

# --- Clase con slots ---
objs_s, t_crea_s, mem_s = bench_create(ConSlots)
t_acc_s, _ = bench_access(objs_s)
print(f"[__slots__]     Crear: {t_crea_s:0.3f}s   Memoria: {mem_s:0.2f} MB   Accesos: {t_acc_s:0.3f}s")

# --- Dataclass con slots ---
objs_d, t_crea_d, mem_d = bench_create(DCSlots)
t_acc_d, _ = bench_access(objs_d)
print(f"[DC slots]      Crear: {t_crea_d:0.3f}s   Memoria: {mem_d:0.2f} MB   Accesos: {t_acc_d:0.3f}s")