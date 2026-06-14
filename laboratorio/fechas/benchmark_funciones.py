"""
=============================================================================
BENCHMARK BRUTO: funciones de fecha — actual vs ordinal vs date nativo
=============================================================================
Responsabilidad:
    Compara cada funcion de fecha individualmente con N repeticiones.
    Sin escenarios compuestos — una funcion, un resultado.

Funciones comparadas:
    Fecha_aNum / to_ordinal / to_date       -> conversion string a fecha
    Num_aFecha / from_ordinal / from_date   -> conversion fecha a string
    Df_Fechas  / resta        / timedelta   -> diferencia en dias
    Sm_Fecha   / suma         / +timedelta  -> suma de dias
    mes()      / mes ordinal  / .month      -> extraccion de mes
    iter rango / range()      / while date  -> iteracion dia a dia (1 año)
=============================================================================
"""

import timeit
from datetime import date, timedelta
from time import mktime, localtime

N       = 1_000_000   # repeticiones por funcion
ANCHO   = 13

# ---------------------------------------------------------------------------
# Datos de entrada fijos (generados una vez)
# ---------------------------------------------------------------------------
_D_STR    = '15062024'                        # string ddmmyyyy
_D_ERP    = None                              # se asigna abajo
_D_ORD    = date(2024, 6, 15).toordinal()
_D_DATE   = date(2024, 6, 15)
_D2_ERP   = None
_D2_ORD   = date(2024, 1, 1).toordinal()
_D2_DATE  = date(2024, 1, 1)
_DIAS     = 47

_INI_ERP  = None
_FIN_ERP  = None
_INI_ORD  = date(2024, 1, 1).toordinal()
_FIN_ORD  = date(2024, 12, 31).toordinal()
_INI_DATE = date(2024, 1, 1)
_FIN_DATE = date(2024, 12, 31)

# ---------------------------------------------------------------------------
# Sistema actual (ERP)
# ---------------------------------------------------------------------------

def Veri_Fecha(d, m, y):
    if m < 1 or m > 12 or d < 1 or d > 31:
        return 0
    if m in (4, 6, 9, 11) and d > 30:
        return 0
    if y < 1 or y > 9999:
        return 0
    if m == 2 and (d > 29 or (not _es_bisiesto(y) and d > 28)):
        return 0
    return 1


def _es_bisiesto(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def Fecha_aNum(v):
    if not v or len(v) < 8:
        return None
    try:
        d, m, y = int(v[:2]), int(v[2:4]), int(v[4:])
    except Exception:
        return None
    if Veri_Fecha(d, m, y):
        return (d - 1) + ((m - 1) * 31) + ((y - 2000) * 372)
    return None


def Num_aFecha(n):
    if n is None:
        return None
    y, v = divmod(int(n), 372)
    m = v // 31
    d = v - (31 * m) + 1
    m += 1
    y += 2000
    if not Veri_Fecha(d, m, y):
        return None
    return f'{str(d).zfill(2)}/{str(m).zfill(2)}/{y}'


def Df_Fechas(f1, f2):
    def dmy(n):
        y, v = divmod(int(n), 372)
        m = v // 31
        d = v - (31 * m) + 1
        return d, m + 1, y + 2000
    d1, m1, y1 = dmy(f1)
    d2, m2, y2 = dmy(f2)
    try:
        t1 = mktime((y1, m1, d1, 2, 0, 0, 0, 0, -1))
        t2 = mktime((y2, m2, d2, 2, 0, 0, 0, 0, -1))
    except Exception:
        return 0
    return int(((t1 - t2) / 86400.0) + 0.5)


def Sm_Fecha(f, masdias):
    y, v = divmod(int(f), 372)
    m = v // 31
    d = v - (31 * m) + 1
    m += 1
    y += 2000
    try:
        t1 = mktime((y, m, d, 2, 0, 0, 0, 0, -1))
    except Exception:
        return f
    t2 = t1 + masdias * 86400.0
    lt = localtime(t2)
    dd, mm, yy = lt[2], lt[1], lt[0]
    return (dd - 1) + ((mm - 1) * 31) + ((yy - 2000) * 372)


def mes_erp(f):
    y, v = divmod(int(f), 372)
    m = v // 31
    return m + 1


def iter_erp(f_ini, f_fin):
    dc = {}
    f = f_ini
    while f <= f_fin:
        dc[f] = 1
        f = Sm_Fecha(f, 1)
    return dc


# ---------------------------------------------------------------------------
# Sistema propuesto (ordinal)
# ---------------------------------------------------------------------------

def iter_ordinal(f_ini, f_fin):
    return {f: 1 for f in range(f_ini, f_fin + 1)}


# ---------------------------------------------------------------------------
# Sistema date nativo
# ---------------------------------------------------------------------------

def iter_date(f_ini, f_fin):
    dc = {}
    f = f_ini
    while f <= f_fin:
        dc[f] = 1
        f += timedelta(days=1)
    return dc


# ---------------------------------------------------------------------------
# Helpers de presentacion
# ---------------------------------------------------------------------------

def _fmt(seg):
    total_ns = seg * 1_000_000_000
    per_call_ns = total_ns / N
    if per_call_ns < 1000:
        per_call = f'{per_call_ns:.0f} ns'
    elif per_call_ns < 1_000_000:
        per_call = f'{per_call_ns/1000:.2f} us'
    else:
        per_call = f'{per_call_ns/1_000_000:.2f} ms'
    total_ms = seg * 1000
    return per_call, f'{total_ms:.1f} ms'


def _speedup(t_base, t_nuevo):
    if t_nuevo == 0:
        return '  inf'
    return f'{t_base / t_nuevo:5.1f}x'


def _row(nombre, t_a, t_n, t_d):
    pca, tota = _fmt(t_a)
    pcn, totn = _fmt(t_n)
    pcd, totd = _fmt(t_d)
    sp_n = _speedup(t_a, t_n)
    sp_d = _speedup(t_a, t_d)
    print(f'{nombre:<26} '
          f'{pca:>{ANCHO}} {tota:>9}   '
          f'{pcn:>{ANCHO}} {totn:>9}  {sp_n}   '
          f'{pcd:>{ANCHO}} {totd:>9}  {sp_d}')


def _header():
    a = f'{"--- ACTUAL ---":^{ANCHO+11}}'
    n = f'{"--- ORDINAL ---":^{ANCHO+17}}'
    d = f'{"--- DATE ---":^{ANCHO+17}}'
    print(f'{"Funcion":<26} {a}  {n}  {d}')
    sub = f'{"":26} {"ns/call":>{ANCHO}} {"total":>9}   {"ns/call":>{ANCHO}} {"total":>9}  {"vs":>6}   {"ns/call":>{ANCHO}} {"total":>9}  {"vs":>6}'
    print(sub)
    print('-' * len(sub))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    global _D_ERP, _D2_ERP, _INI_ERP, _FIN_ERP

    _D_ERP   = Fecha_aNum(_D_STR)
    _D2_ERP  = Fecha_aNum('01012024')
    _INI_ERP = Fecha_aNum('01012024')
    _FIN_ERP = Fecha_aNum('31122024')

    print(f'\nBENCHMARK BRUTO — {N:,} repeticiones por funcion\n')
    _header()

    # Fecha_aNum / toordinal / date()
    t_a = timeit.timeit(lambda: Fecha_aNum(_D_STR), number=N)
    t_n = timeit.timeit(lambda: date(2024, 6, 15).toordinal(), number=N)
    t_d = timeit.timeit(lambda: date(2024, 6, 15), number=N)
    _row('Fecha_aNum / to_ordinal', t_a, t_n, t_d)

    # Num_aFecha / fromordinal / fromordinal+fmt
    t_a = timeit.timeit(lambda: Num_aFecha(_D_ERP), number=N)
    t_n = timeit.timeit(lambda: date.fromordinal(_D_ORD).strftime('%d/%m/%Y'), number=N)
    t_d = timeit.timeit(lambda: _D_DATE.strftime('%d/%m/%Y'), number=N)
    _row('Num_aFecha / fromordinal', t_a, t_n, t_d)

    # Df_Fechas / resta / timedelta.days
    t_a = timeit.timeit(lambda: Df_Fechas(_D_ERP, _D2_ERP), number=N)
    t_n = timeit.timeit(lambda: _D_ORD - _D2_ORD, number=N)
    t_d = timeit.timeit(lambda: (_D_DATE - _D2_DATE).days, number=N)
    _row('Df_Fechas / resta', t_a, t_n, t_d)

    # Sm_Fecha / suma int / +timedelta
    t_a = timeit.timeit(lambda: Sm_Fecha(_D_ERP, _DIAS), number=N)
    t_n = timeit.timeit(lambda: _D_ORD + _DIAS, number=N)
    t_d = timeit.timeit(lambda: _D_DATE + timedelta(days=_DIAS), number=N)
    _row('Sm_Fecha / suma', t_a, t_n, t_d)

    # mes() / fromordinal.month / .month
    t_a = timeit.timeit(lambda: mes_erp(_D_ERP), number=N)
    t_n = timeit.timeit(lambda: date.fromordinal(_D_ORD).month, number=N)
    t_d = timeit.timeit(lambda: _D_DATE.month, number=N)
    _row('mes()', t_a, t_n, t_d)

    # iter dia/dia 1 año — menos repeticiones por coste
    NI = max(1, N // 1000)
    t_a = timeit.timeit(lambda: iter_erp(_INI_ERP, _FIN_ERP), number=NI)   / NI
    t_n = timeit.timeit(lambda: iter_ordinal(_INI_ORD, _FIN_ORD), number=NI) / NI
    t_d = timeit.timeit(lambda: iter_date(_INI_DATE, _FIN_DATE), number=NI)  / NI
    # mostrar como si fueran N=1 (son tiempos absolutos de 1 iteracion)
    fN = N
    globals()['N'] = 1
    _row('iter 1 año ('+str(NI)+' vez)', t_a, t_n, t_d)
    globals()['N'] = fN

    print()


if __name__ == '__main__':
    run()
