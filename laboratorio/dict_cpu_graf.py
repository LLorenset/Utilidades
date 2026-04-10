# ----------------------------------------------------------
# grafico_bench.py
# Benchmark + gráfico de Método A vs Método B (Python 3.13)
# ----------------------------------------------------------
import time
import random
import matplotlib.pyplot as plt

# ------------------------------
# Métodos a comparar
# ------------------------------
def metodo_A(nombres, valores):
    return {sub[0]: valor for sub, valor in zip(nombres, valores)}

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

# ------------------------------
# Benchmark simple por tamaños
# ------------------------------
def run_bench():
    sizes = [100, 200, 400, 800, 1600, 3200, 6400]
    A_times = []
    B_times = []

    for N in sizes:
        # generar datos
        valores = [str(random.random()) for _ in range(N)]
        nombres = [[f"campo_{i}"] for i in range(N)]
        core = {0: [[f"campo_{i}"] for i in range(N)]}
        fi = 0

        # Método A
        t0 = time.perf_counter()
        metodo_A(nombres, valores)
        A_times.append(time.perf_counter() - t0)

        # Método B
        t0 = time.perf_counter()
        metodo_B(core, fi, valores)
        B_times.append(time.perf_counter() - t0)

        print(f"N={N}  A={A_times[-1]:.6f}s  B={B_times[-1]:.6f}s")

    return sizes, A_times, B_times

# ------------------------------
# Dibujar gráfico
# ------------------------------
def plot_results(sizes, A_times, B_times):
    plt.figure(figsize=(8,5))
    plt.plot(sizes, A_times, marker='o', label='Método A (dict + zip)')
    plt.plot(sizes, B_times, marker='o', label='Método B (for + try/except)')
    plt.xlabel("Tamaño N")
    plt.ylabel("Tiempo (segundos)")
    plt.title("Benchmark: Método A vs Método B")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("grafico_bench.png")
    print("\n📁 Gráfico guardado como: grafico_bench.png")

# ------------------------------
# Main
# ------------------------------
if __name__ == "__main__":
    sizes, A_times, B_times = run_bench()
    plot_results(sizes, A_times, B_times)