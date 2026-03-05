import time

import numpy as np

t0 = time.perf_counter()
n = 10_000_000
t1 = time.perf_counter()
a = np.random.rand(n)
t2 = time.perf_counter()
b = np.random.rand(n)
t3 = time.perf_counter()

# Vectorizado (rápido, C por debajo)
c = a + b
t4 = time.perf_counter()

# Bucle Python (lento)
c_py = [ai + bi for ai, bi in zip(a, b)]
t5 = time.perf_counter()

print(f"Tiempo generación a: {t2-t1:.4f} s")
print(f"Tiempo generación b: {t3-t2:.4f} s")
print(f"Tiempo vectorizado: {t4-t3:.4f} s")
print(f"Tiempo bucle python: {t5-t4:.4f} s")
print(f"Tiempo total: {t5-t0:.4f} s")
