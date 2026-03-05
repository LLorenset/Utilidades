import time
import tracemalloc
from dataclasses import dataclass

N = 10_000_000  # número de instancias


# --------------------------
# Clase normal (sin slots)
# --------------------------
class Normal:
    def __init__(self, a, b):
        self.a = a
        self.b = b


# --------------------------
# Clase con __slots__
# --------------------------
class ConSlots:
    __slots__ = ("a", "b")
    def __init__(self, a, b):
        self.a = a
        self.b = b


# --------------------------
# Dataclass con slots
# --------------------------
@dataclass(slots=True)
class DCSlots:
    a: int
    b: int


# Función de benchmark genérica
def benchmark(cls):
    tracemalloc.start()
    t0 = time.perf_counter()

    objs = [cls(i, i+1) for i in range(N)]

    t1 = time.perf_counter()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return t1 - t0, peak / (1024 * 1024)  # segundos, MB


# Ejecutamos benchmarks
print(f"Creando {N:,} instancias...\n")

t_norm, mem_norm = benchmark(Normal)
print(f"Clase normal:     {t_norm:0.3f}s   pico memoria: {mem_norm:0.2f} MB")

t_slots, mem_slots = benchmark(ConSlots)
print(f"Con __slots__:     {t_slots:0.3f}s   pico memoria: {mem_slots:0.2f} MB")

t_dc, mem_dc = benchmark(DCSlots)
print(f"Dataclass slots:   {t_dc:0.3f}s   pico memoria: {mem_dc:0.2f} MB")
