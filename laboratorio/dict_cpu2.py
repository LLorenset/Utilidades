# bench_total.py — Benchmark completo A vs B con tiempo total, CPU%, CPU-time y memoria.
import argparse, gc, os, random, string, threading, time
from time import perf_counter, process_time
import psutil
from statistics import mean, median

# -------------------------------------------------------
# Generación de datos
# -------------------------------------------------------
def rnd(n=12):
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))

def build_data(size, extra_names=0, extra_values=0, seed=42):
    random.seed(seed)
    valores = [rnd(16) for _ in range(size)]
    nombres = [[f"campo_{i}", "x", "y"] for i in range(size)]

    if extra_names:
        nombres.extend([[f"extra_nom_{i}"] for i in range(extra_names)])
    if extra_values:
        valores.extend([rnd(16) for _ in range(extra_values)])

    core = {0: [[f"campo_{i}"] for i in range(len(nombres))]}
    fi = 0
    rg = list(valores)
    return nombres, valores, core, fi, rg

# -------------------------------------------------------
# Métodos bajo test
# -------------------------------------------------------
def metodo_A(nombres, valores):
    return {sub[0]: valor for sub, valor in zip(nombres, valores)}

def metodo_B(core, fi, rg):
    v = {}
    lr = len(rg)
    for k in range(lr):
        try:
            ncam = core[fi][k][0]
            v[ncam] = rg[k]
        except Exception:
            pass
    return v

# -------------------------------------------------------
# Medición CPU% en paralelo
# -------------------------------------------------------
proc = psutil.Process(os.getpid())

def sample_cpu_percent(stop_event, interval, samples_list):
    proc.cpu_percent(None)  # arranca el delta
    while not stop_event.is_set():
        samples_list.append(proc.cpu_percent(interval=interval))

# -------------------------------------------------------
# Medición completa por iteración
# -------------------------------------------------------
def measure(func, sample_interval, target_samples, *args, **kwargs):
    gc.collect()
    time.sleep(0.003)

    rss0 = proc.memory_info().rss
    cpu_t0 = process_time()
    t0 = perf_counter()

    cpu_pct_samples = []
    stop_evt = threading.Event()
    sampler = None

    if target_samples > 0:
        sampler = threading.Thread(
            target=sample_cpu_percent,
            args=(stop_evt, sample_interval, cpu_pct_samples),
            daemon=True
        )
        sampler.start()

    result = func(*args, **kwargs)

    dt = perf_counter() - t0
    cpu_dt = process_time() - cpu_t0
    rss1 = proc.memory_info().rss
    mem_used = rss1 - rss0

    if sampler:
        stop_evt.set()
        sampler.join()

    avg_cpu_pct = mean(cpu_pct_samples) if cpu_pct_samples else 0.0
    max_cpu_pct = max(cpu_pct_samples) if cpu_pct_samples else 0.0

    return {
        "time": dt,
        "cpu_time": cpu_dt,
        "mem": mem_used,
        "cpu_pct_avg": avg_cpu_pct,
        "cpu_pct_max": max_cpu_pct,
        "size": len(result),
    }

# -------------------------------------------------------
# Resumen por método
# -------------------------------------------------------
def summarize(samples, label):
    def stats_of(key):
        vals = [s[key] for s in samples]
        return min(vals), median(vals), mean(vals), max(vals)

    t_min, t_p50, t_mean, t_max = stats_of("time")
    c_min, c_p50, c_mean, c_max = stats_of("cpu_time")
    p_min, p_p50, p_mean, p_max = stats_of("cpu_pct_avg")
    m_min, m_p50, m_mean, m_max = stats_of("mem")

    print(f"\n[{label}]")
    print(f"  wall-time (s):   min={t_min:.6f}  p50={t_p50:.6f}  mean={t_mean:.6f}  max={t_max:.6f}")
    print(f"  cpu-time  (s):   min={c_min:.6f}  p50={c_p50:.6f}  mean={c_mean:.6f}  max={c_max:.6f}")
    print(f"  CPU% (avg):      min={p_min:6.2f} p50={p_p50:6.2f} mean={p_mean:6.2f} max={p_max:6.2f}")
    print(f"  Mem delta (B):   min={m_min}  p50={int(m_p50)}  mean={int(m_mean)}  max={m_max}")

# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Benchmark total A vs B (tiempo total, CPU, memoria, CPU%)")
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--size", type=int, default=200000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--extra-names", type=int, default=0)
    ap.add_argument("--extra-values", type=int, default=0)
    ap.add_argument("--sample-interval", type=float, default=0.02)
    ap.add_argument("--cpu-samples", type=int, default=20)
    args = ap.parse_args()

    print(f"- iters={args.iters} size={args.size} seed={args.seed}")
    print(f"- extra_names={args.extra_names}  extra_values={args.extra_values}")
    print(f"- sample_interval={args.sample_interval}s  cpu_samples={args.cpu_samples}")

    nombres, valores, core, fi, rg = build_data(
        args.size, args.extra_names, args.extra_values, args.seed
    )

    print(f"- len(nombres)={len(nombres)}, len(valores)={len(valores)}")

    # Warm-up
    measure(metodo_A, args.sample_interval, 4, nombres, valores)
    measure(metodo_B, args.sample_interval, 4, core, fi, rg)

    samples_A, samples_B = [], []

    # -------------------------
    # TIEMPO TOTAL A
    # -------------------------
    total_A_start = perf_counter()
    for _ in range(args.iters):
        samples_A.append(measure(metodo_A, args.sample_interval, args.cpu_samples, nombres, valores))
    total_A = perf_counter() - total_A_start

    # -------------------------
    # TIEMPO TOTAL B
    # -------------------------
    total_B_start = perf_counter()
    for _ in range(args.iters):
        samples_B.append(measure(metodo_B, args.sample_interval, args.cpu_samples, core, fi, rg))
    total_B = perf_counter() - total_B_start

    # -------------------------
    # Impresión resultados
    # -------------------------
    print(f"\n⏱️ Tiempo TOTAL Método A: {total_A:.6f} s")
    print(f"⏱️ Tiempo TOTAL Método B: {total_B:.6f} s")
    print(f"📊 Diferencia (B - A):    {total_B - total_A:+.6f} s")

    print(f"\nTamaño dict A (última iteración): {samples_A[-1]['size']}")
    print(f"Tamaño dict B (última iteración): {samples_B[-1]['size']}")

    summarize(samples_A, "Método A  (dict comprehension + zip)")
    summarize(samples_B, "Método B  (for + try/except)")

if __name__ == "__main__":
    main()