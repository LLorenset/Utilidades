import time

N = 10_000_000      # instancias
ACC = 50_000_000    # accesos para medir velocidad


# ----------------------
# Clase normal sin property
# ----------------------
class Normal:
    def __init__(self, a):
        self.a = a


# ----------------------
# Clase con property simple
# ----------------------
class PropSimple:
    def __init__(self, a):
        self._a = a

    @property
    def a(self):
        return self._a


# ----------------------
# Clase con property + validación
# ----------------------
class PropValid:
    def __init__(self, a):
        self._a = a

    @property
    def a(self):
        # lógica extra (mínima)
        if self._a < 0:   # validación inventada para medir coste
            return 0
        return self._a


def crea_objs(cls):
    return [cls(i) for i in range(N)]


def bench_access(objs):
    t0 = time.perf_counter()
    total = 0
    for i in range(ACC):
        total += objs[i % N].a
    t1 = time.perf_counter()
    return t1 - t0, total


print(f"### Acceso a atributos en {ACC:,} lecturas ###\n")

# --- Normal ---
objs_n = crea_objs(Normal)
t_n, _ = bench_access(objs_n)
print(f"[Normal]       Acceso: {t_n:0.3f}s")

# --- Property simple ---
objs_ps = crea_objs(PropSimple)
t_ps, _ = bench_access(objs_ps)
print(f"[PropSimple]   Acceso: {t_ps:0.3f}s")

# --- Property con validación ---
objs_pv = crea_objs(PropValid)
t_pv, _ = bench_access(objs_pv)
print(f"[PropValid]    Acceso: {t_pv:0.3f}s")
