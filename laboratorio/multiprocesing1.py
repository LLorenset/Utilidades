
from concurrent.futures import ProcessPoolExecutor
import time

def pesado(n):
    s = 0
    for i in range(n):
        s += (i*i) % 97
    return s

if __name__ == "__main__":
    number = 2_000_000
    t0 = time.perf_counter()
    with ProcessPoolExecutor() as ex:
        print(sum(ex.map(pesado, [number]*8)))

    t1 = time.perf_counter()

    print(pesado(number)+pesado(number)+pesado(number)+pesado(number)+
          pesado(number)+pesado(number)+pesado(number)+pesado(number))
    t2 = time.perf_counter()

    print(f"Tiempo multiprocesing: {t1-t0:.4f} s")
    print(f"Tiempo secuencial: {t2-t1:.4f} s")
    print(f"Tiempo total: {t2-t0:.4f} s")
    