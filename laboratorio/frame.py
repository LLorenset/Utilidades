import time


def procesa(lista):
    # función "cara" conceptualmente, pero que casi siempre no hace nada
    for _ in lista:
        pass


def procesa2(lista):
    # función "cara" conceptualmente, pero que casi siempre no hace nada
    if not lista:
        return
    for _ in lista:
        pass


def test_llamar_siempre(lista, n):
    t0 = time.perf_counter()
    for _ in range(n):
        procesa(lista)
    t1 = time.perf_counter()
    return t1 - t0

def test_llamar_siempre2(lista, n):
    t0 = time.perf_counter()
    for _ in range(n):
        procesa2(lista)
    t1 = time.perf_counter()
    return t1 - t0


def test_if_antes(lista, n):
    t0 = time.perf_counter()
    for _ in range(n):
        if lista:
            procesa(lista)
    t1 = time.perf_counter()
    return t1 - t0


if __name__ == "__main__":
    lista_vacia = []
    n = 1_000_000

    t1 = test_llamar_siempre(lista_vacia, n)
    t2 = test_if_antes(lista_vacia, n)

    #t3 = test_llamar_siempre2(lista_vacia, n)


    print(f"Llamar siempre a la función: {t1:.3f} s")
    print(f"If antes de llamar:        {t2:.3f} s")
    print(f"Ahorro:                   {t1 - t2:.3f} s")
    #print(f"Llamar siempre a la función (procesa2): {t3:.3f} s")
