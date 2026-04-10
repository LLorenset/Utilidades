# bench_uv.py  (Python 3.13)
import argparse
import gc
import os
import random
import string
import time
from time import perf_counter
import psutil
import statistics as stats

# -------------------------------
# Generación de datos de prueba
# -------------------------------
def gen_random_str(n=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))

def build_data(size, extra_names=0, extra_values=0, seed=42):
    random.seed(seed)

    # valores: strings aleatorios
    valores = [gen_random_str(16) for _ in range(size)]
    # nombres: lista de listas, 1ª columna es la clave
    nombres = [[f"campo_{i}", "x", "y"] for i in range(size)]

    # desbalances opcionales
    if extra_names > 0:
        nombres.extend([[f"extra_nom_{i}"] for i in range(extra_names)])
    if extra_values > 0:
        valores.extend([gen_random_str(16) for _ in range(extra_values)])

    # Simulación mínima de core.Dc[fi] para Método B
    core = {0: [[f"campo_{i}"] for i in range(len(nombres))]}
    fi = 0
    rg = list(valores)  # alias del patrón original

    return nombres, valores, core, fi, rg

# -------------------------------
# Métodos bajo test
# -------------------------------
def metodo_A(nombres, valores):
    # Dict comprehension + zip (trunca a la menor longitud)
    return {sub[0]: valor for sub, valor in zip(nombres, valores)}

def metodo_B(core, fi, rg):
    # Bucle for con try/except (como tu aproximación)
    v = {}
    lr = len(rg)
    for k in range(lr):
        try:
            ncam = core[fi][k][0]
            v[ncam] = rg[k]
        except Exception:
            # Cualquier desbalance/índice fuera de rango se ignora
            pass
    return v

# -------------------------------
# Medición (tiempo, CPU, memoria)
# -------------------------------
_proc = psutil.Process(os.getpid())

def measure(func, *args, **kwargs):
    gc.collect()
  #  time.sleep(0.001)  # estabilizar RSS

    rss0 = _proc.memory_info().rss
    cpu0 = _proc.cpu_times()  # user+system
    t0 = perf_counter()

    result = func(*args, **kwargs)

    dt = perf_counter() - t0
    cpu1 = _proc.cpu_times()
    rss1 = _proc.memory_info().rss

    cpu_used = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    mem_used = rss1 - rss0  # delta RSS (bytes, puede ser 0 o negativo si GC libera)

    return {"time": dt, "cpu": cpu_used, "mem": mem_used, "size": len(result)}

# -------------------------------
# Utilidades de informe
# -------------------------------
def summarize(samples, label):
    times = [s["time"] for s in samples]
    cpus  = [s["cpu"]  for s in samples]
    mems  = [s["mem"]  for s in samples]

    def fmt_stats(vals):
        return {
            "min": min(vals),
            "p50": stats.median(vals),
            "mean": stats.mean(vals),
            "max": max(vals),
        }

    tstats = fmt_stats(times)
    cstats = fmt_stats(cpus)
    mstats = fmt_stats(mems)

    print(f"\n[{label}]")
    print(f"  tiempo (s):  min={tstats['min']:.6f}  p50={tstats['p50']:.6f}  mean={tstats['mean']:.6f}  max={tstats['max']:.6f}")
    print(f"  CPU (s):     min={cstats['min']:.6f}  p50={cstats['p50']:.6f}  mean={cstats['mean']:.6f}  max={cstats['max']:.6f}")
    print(f"  Mem (bytes): min={mstats['min']}  p50={mstats['p50']}  mean={int(mstats['mean'])}  max={mstats['max']}")

def main():
    ap = argparse.ArgumentParser(description="Benchmark de métodos A vs B (tiempo/CPU/memoria) con longitudes dinámicas")
    ap.add_argument("--iters", type=int, default=20, help="nº de iteraciones por método (default: 20)")
    ap.add_argument("--size", type=int, default=200000, help="tamaño base de las listas (default: 200000)")
    ap.add_argument("--seed", type=int, default=42, help="semilla de aleatoriedad (default: 42)")
    ap.add_argument("--extra-names", type=int, default=0, help="añadir sublistas extra a 'nombres'")
    ap.add_argument("--extra-values", type=int, default=0, help="añadir valores extra a 'valores'")
    args = ap.parse_args()

    print(f"- iters={args.iters}  size={args.size}  seed={args.seed}  extra_names={args.extra_names}  extra_values={args.extra_values}")

    # Datos de base
    nombres, valores, core, fi, rg = build_data(args.size, args.extra_names, args.extra_values, args.seed)
    print(f"- len(nombres)={len(nombres)}  len(valores)={len(valores)}")

    # Warm-up ligero para estabilizar importes/cachés
    measure(metodo_A, nombres, valores)
    measure(metodo_B, core, fi, rg)

    # Benchmark
    samples_A, samples_B = [], []

    for _ in range(args.iters):
        samples_A.append(measure(metodo_A, nombres, valores))
    for _ in range(args.iters):
        samples_B.append(measure(metodo_B, core, fi, rg))

    # Comprobación simple de tamaños generados
    print(f"- tamaño dict A (última iter): {samples_A[-1]['size']}")
    print(f"- tamaño dict B (última iter): {samples_B[-1]['size']}")

    # Resumen
    summarize(samples_A, "Método A  (dict comprehension + zip)")
    summarize(samples_B, "Método B  (for + try/except)")

if __name__ == "__main__":
    main()


    # Más nombres que valores (se ignoran los sobrantes)
#python dict_cpu.py --iters 20 --size 100000 --extra-names 5000

# Más valores que nombres (se ignoran los sobrantes)
#python dict_cpu.py --iters 20 --size 100000 --extra-values 5000