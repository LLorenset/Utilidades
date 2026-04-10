import time
import random

def metodo_A(nombres, valores):
    # Python 3.13 (dict comprehension)
    try:
        return { sub[0]: valor for sub, valor in zip(nombres, valores) }
    except SyntaxError:
        # Python 2.7 fallback
       # return dict((sub[0], valor) for sub, valor in zip(nombres, valores))
       pass

def metodo_B(core, fi, rg):
    v = {}
    lr = len(rg)
    for k in range(lr):
        try:
            ncam = core[fi][k][0]
            v[ncam] = rg[k]
        except:
            pass
    return v

# -------------------------------------
# CONFIGURACIÓN DEL TEST
# -------------------------------------
ITERACIONES = 2000
N = 50  # tamaño de las listas

# Datos dinámicos
valores = [str(random.random()) for _ in range(N)]
nombres = [["campo_%d" % i, "x"] for i in range(N)]

# Equivalente a core.Dc[fi]
core = {0: [[ "campo_%d" % i ] for i in range(N)]}
fi = 0

# -------------------------------------
# BENCHMARK
# -------------------------------------
tA_total = 0
tB_total = 0

t0 = time.time()
for _ in range(ITERACIONES):
    # Método A
    dA = metodo_A(nombres, valores)
tA_total += time.time() - t0

t0 = time.time()
for _ in range(ITERACIONES):
    # Método B
    dB = metodo_B(core, fi, valores)
tB_total += time.time() - t0

# -------------------------------------
# RESULTADOS
# -------------------------------------
print("Ejecutado %d veces con tamaño N=%d" % (ITERACIONES, N))
print("Método A (dict comprehension + zip):     %.6f s" % tA_total)
print("Método B (for + try/except):             %.6f s" % tB_total)
print("A es %.2fx más rápido" % (tB_total / tA_total))