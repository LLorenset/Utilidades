"""
=============================================================================
BENCHMARK: Formato de fechas ERP actual vs formato ordinal propuesto
=============================================================================
Responsabilidad:
    Compara el rendimiento del sistema de fechas actual del servidor ERP
    (entero propio: d + m*31 + y*372, base 2000) frente al formato propuesto
    (ordinal Python estándar: date.toordinal(), centinela -1 para nulo).

Escenario simulado:
    Replica los patrones de uso de fechas de a_estadisticas(arg) sin acceso
    a base de datos:
      - Bucle sobre N registros con rango de fechas (simula ls_registros)
      - Cálculo de diferencia de días entre fecha de registro y fecha límite
      - Suma de días para calcular vencimientos (Sm_Fecha / +n)
      - Iteración día a día sobre un rango de un año (dc_inifin)
      - Clasificación de registro en tramo mensual (m // 31 vs date.month)
      - Triple ejercicio fiscal (mismo bucle x3, patrón gpx/gpz/gpy)

Diseño:
    Cada escenario tiene versión _actual (usa Fecha_aNum/Num_aFecha/mktime)
    y versión _nuevo (usa ordinal date.toordinal(), aritmética directa).
    timeit mide cada versión con el mismo conjunto de datos de entrada.
    Los datos de entrada se generan una sola vez fuera del benchmark.

Formato ERP actual:
    n = (d-1) + (m-1)*31 + (y-2000)*372
    No es aritméticamente correcto (meses de 31 días fijos) → cualquier
    operación distinta de comparar requiere conversión a mktime.

Formato propuesto:
    n = date(y, m, d).toordinal()   # entero secuencial gregoriano real
    -1 = fecha nula (centinela, ningún ordinal real es negativo)
    Aritmética directa: f2-f1, f+n, range(f1,f2) sin conversiones.
=============================================================================
"""

import timeit
from datetime import date, timedelta
from time import mktime

# ---------------------------------------------------------------------------
# Dependencias inline de fechas.py del servidor (ajus0, lista no se usan
# en las operaciones de benchmark — se incluyen las funciones puras)
# ---------------------------------------------------------------------------

# ===== SISTEMA ACTUAL =======================================================

def _ajus0(s: str, l: int) -> str:
    res = s.zfill(int(l))
    la = len(res)
    if la > l:
        res = res[la - l:]
    return res


def Veri_Fecha(d: int, m: int, y: int) -> int:
    if m < 1 or m > 12 or d < 1 or d > 31:
        return 0
    if m in (4, 6, 9, 11) and d > 30:
        return 0
    if y < 1 or y > 9999:
        return 0
    if m == 2 and (d > 29 or (not es_bisiesto(y) and d > 28)):
        return 0
    return 1


def es_bisiesto(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def Fecha_aNum(v: str) -> int | None:
    """Convierte string 'ddmmyyyy' a entero ERP."""
    if v == '':
        return None
    if len(v) < 8:
        return None
    try:
        d, m, y = int(v[:2]), int(v[2:4]), int(v[4:])
    except Exception:
        return None
    if Veri_Fecha(d, m, y):
        return (d - 1) + ((m - 1) * 31) + ((y - 2000) * 372)
    return None


def Num_aFecha_dmy(n: int) -> tuple[int, int, int] | None:
    """Convierte entero ERP a (d, m, y)."""
    if n is None:
        return None
    n = int(n)
    y, v = divmod(n, 372)
    m = v // 31
    d = v - (31 * m) + 1
    m += 1
    y += 2000
    if not Veri_Fecha(d, m, y):
        return None
    return d, m, y


def Df_Fechas_actual(f1: int, f2: int) -> int:
    """Diferencia en días entre dos fechas ERP. Coste: 2x Num_aFecha + 2x mktime."""
    d1, m1, y1 = Num_aFecha_dmy(f1)
    d2, m2, y2 = Num_aFecha_dmy(f2)
    try:
        t1 = mktime((y1, m1, d1, 2, 0, 0, 0, 0, -1))
        t2 = mktime((y2, m2, d2, 2, 0, 0, 0, 0, -1))
    except Exception:
        return 0
    return int(((t1 - t2) / 86400.0) + 0.5)


def Sm_Fecha_actual(f: int, masdias: int) -> int:
    """Suma días a fecha ERP. Coste: Num_aFecha + mktime + Fecha_aNum."""
    d, m, y = Num_aFecha_dmy(f)
    try:
        t1 = mktime((y, m, d, 2, 0, 0, 0, 0, -1))
    except Exception:
        return f
    t2 = t1 + masdias * 86400.0
    from time import localtime
    lt = localtime(t2)
    dd, mm, yy = lt[2], lt[1], lt[0]
    return (dd - 1) + ((mm - 1) * 31) + ((yy - 2000) * 372)


def mes_erp(f: int) -> int:
    """Extrae mes de fecha ERP. Coste: Num_aFecha."""
    _, m, _ = Num_aFecha_dmy(f)
    return m


# ===== SISTEMA PROPUESTO ====================================================
# Ordinal Python: date.toordinal(). Centinela: -1 (nulo).
# Conversión solo al ingresar/mostrar.

NULO = -1  # centinela fecha nula


def fecha_a_ordinal(y: int, m: int, d: int) -> int:
    """Convierte (y,m,d) a ordinal. Solo en capa de entrada."""
    return date(y, m, d).toordinal()


def ordinal_a_dmy(n: int) -> tuple[int, int, int]:
    """Convierte ordinal a (d,m,y). Solo en capa de presentación."""
    dt = date.fromordinal(n)
    return dt.day, dt.month, dt.year


def Df_Fechas_nuevo(f1: int, f2: int) -> int:
    """Diferencia en días. Coste: resta directa."""
    return f1 - f2


def Sm_Fecha_nuevo(f: int, masdias: int) -> int:
    """Suma días. Coste: suma directa."""
    return f + masdias


def mes_ordinal(f: int) -> int:
    """Extrae mes de ordinal. Coste: date.fromordinal (solo cuando se necesita mostrar)."""
    return date.fromordinal(f).month


# ===== SISTEMA DATE NATIVO ==================================================
# Registros almacenan objetos date directamente.
# Diferencia: f2 - f1 devuelve timedelta; suma: f + timedelta(days=n).

def Df_Fechas_date(f1: date, f2: date) -> int:
    """Diferencia en días. Coste: resta de date -> timedelta -> .days"""
    return (f1 - f2).days


def Sm_Fecha_date(f: date, masdias: int) -> date:
    """Suma días. Coste: timedelta construction + date.__add__."""
    return f + timedelta(days=masdias)


# ---------------------------------------------------------------------------
# Generación de datos de prueba (fuera del benchmark)
# ---------------------------------------------------------------------------

def _generar_registros_actual(n: int) -> list[tuple[int, int, int, float]]:
    """
    Genera n registros simulados en formato ERP actual.
    Cada registro: (fecha_llamada, fecha_cierre, minutos, valoracion)
    Rango: año 2024 completo, distribuidos uniformemente.
    """
    registros = []
    inicio = date(2024, 1, 1)
    for i in range(n):
        dt_ini = inicio + timedelta(days=i % 365)
        dt_fin = dt_ini + timedelta(days=(i % 30) + 1)
        f_ini = Fecha_aNum(dt_ini.strftime('%d%m%Y'))
        f_fin = Fecha_aNum(dt_fin.strftime('%d%m%Y'))
        minutos = 15 + (i % 120)
        valoracion = (i % 5) + 1
        registros.append((f_ini, f_fin, minutos, float(valoracion)))
    return registros


def _generar_registros_date(n: int) -> list[tuple[date, date, int, float]]:
    """Genera n registros con objetos date nativos. Mismos datos."""
    registros = []
    inicio = date(2024, 1, 1)
    for i in range(n):
        dt_ini = inicio + timedelta(days=i % 365)
        dt_fin = dt_ini + timedelta(days=(i % 30) + 1)
        minutos = 15 + (i % 120)
        valoracion = (i % 5) + 1
        registros.append((dt_ini, dt_fin, minutos, float(valoracion)))
    return registros


def _generar_registros_nuevo(n: int) -> list[tuple[int, int, int, float]]:
    """
    Genera n registros en formato ordinal propuesto.
    Mismos datos que _generar_registros_actual.
    """
    registros = []
    inicio = date(2024, 1, 1)
    for i in range(n):
        dt_ini = inicio + timedelta(days=i % 365)
        dt_fin = dt_ini + timedelta(days=(i % 30) + 1)
        f_ini = dt_ini.toordinal()
        f_fin = dt_fin.toordinal()
        minutos = 15 + (i % 120)
        valoracion = (i % 5) + 1
        registros.append((f_ini, f_fin, minutos, float(valoracion)))
    return registros


# ---------------------------------------------------------------------------
# Escenario 1: Bucle principal — simula procesamiento de ls_registros
# Para cada registro: calcula días abierto, vencimiento a 30 días,
# clasifica por mes, acumula por mes y tipo.
# Triple ejercicio fiscal (gpx/gpz/gpy) = mismo bucle x3.
# ---------------------------------------------------------------------------

def escenario1_actual(registros: list, fecha_limite: int) -> dict:
    """Procesa registros en formato ERP actual."""
    dc_meses = {}
    dc_vencimientos = {}

    for ejercicio_registros in (registros, registros, registros):  # triple ejercicio
        for f_ini, f_fin, minutos, valoracion in ejercicio_registros:
            dias_abierto = Df_Fechas_actual(f_fin, f_ini)
            vencimiento = Sm_Fecha_actual(f_ini, 30)
            en_plazo = vencimiento >= fecha_limite
            mes = mes_erp(f_ini)

            clave = (mes, en_plazo)
            if clave not in dc_meses:
                dc_meses[clave] = [0, 0, 0.0]
            dc_meses[clave][0] += 1
            dc_meses[clave][1] += dias_abierto
            dc_meses[clave][2] += valoracion

            if dias_abierto > 5:
                if mes not in dc_vencimientos:
                    dc_vencimientos[mes] = 0
                dc_vencimientos[mes] += 1

    return dc_meses


def escenario1_date(registros: list, fecha_limite: date) -> dict:
    """Procesa registros con objetos date nativos."""
    dc_meses = {}
    dc_vencimientos = {}

    for ejercicio_registros in (registros, registros, registros):
        for f_ini, f_fin, minutos, valoracion in ejercicio_registros:
            dias_abierto = Df_Fechas_date(f_fin, f_ini)
            vencimiento = Sm_Fecha_date(f_ini, 30)
            en_plazo = vencimiento >= fecha_limite
            mes = f_ini.month

            clave = (mes, en_plazo)
            if clave not in dc_meses:
                dc_meses[clave] = [0, 0, 0.0]
            dc_meses[clave][0] += 1
            dc_meses[clave][1] += dias_abierto
            dc_meses[clave][2] += valoracion

            if dias_abierto > 5:
                if mes not in dc_vencimientos:
                    dc_vencimientos[mes] = 0
                dc_vencimientos[mes] += 1

    return dc_meses


def escenario1_nuevo(registros: list, fecha_limite: int) -> dict:
    """Procesa registros en formato ordinal propuesto."""
    dc_meses = {}
    dc_vencimientos = {}

    for ejercicio_registros in (registros, registros, registros):  # triple ejercicio
        for f_ini, f_fin, minutos, valoracion in ejercicio_registros:
            dias_abierto = Df_Fechas_nuevo(f_fin, f_ini)
            vencimiento = Sm_Fecha_nuevo(f_ini, 30)
            en_plazo = vencimiento >= fecha_limite
            # mes: solo se necesita al clasificar — en producción se evitaría
            # si la clave fuera el ordinal del primer día del mes
            mes = date.fromordinal(f_ini).month

            clave = (mes, en_plazo)
            if clave not in dc_meses:
                dc_meses[clave] = [0, 0, 0.0]
            dc_meses[clave][0] += 1
            dc_meses[clave][1] += dias_abierto
            dc_meses[clave][2] += valoracion

            if dias_abierto > 5:
                if mes not in dc_vencimientos:
                    dc_vencimientos[mes] = 0
                dc_vencimientos[mes] += 1

    return dc_meses


# ---------------------------------------------------------------------------
# Escenario 2: Iteración día a día sobre un año — simula dc_inifin
# Para cada día del año: comprueba si hay registros activos en ese día,
# calcula días hábiles acumulados (excluye fin de semana).
# ---------------------------------------------------------------------------

def escenario2_actual(f_inicio: int, f_fin: int) -> dict:
    """Itera día a día en formato ERP actual."""
    dc = {}
    f = f_inicio
    acum = 0
    while f <= f_fin:
        dmy = Num_aFecha_dmy(f)
        if dmy:
            d, m, y = dmy
            # día de semana vía mktime
            t = mktime((y, m, d, 2, 0, 0, 0, 0, -1))
            from time import localtime
            dia_semana = localtime(t)[6]
            if dia_semana < 5:  # lunes-viernes
                acum += 1
            dc[f] = acum
        f = Sm_Fecha_actual(f, 1)  # +1 día: coste mktime completo
    return dc


def escenario2_date(f_inicio: date, f_fin: date) -> dict:
    """Itera día a día con objetos date nativos."""
    dc = {}
    acum = 0
    f = f_inicio
    while f <= f_fin:
        if f.weekday() < 5:
            acum += 1
        dc[f] = acum
        f += timedelta(days=1)
    return dc


def escenario2_nuevo(f_inicio: int, f_fin: int) -> dict:
    """Itera día a día en formato ordinal propuesto."""
    dc = {}
    acum = 0
    for f in range(f_inicio, f_fin + 1):
        dt = date.fromordinal(f)
        if dt.weekday() < 5:  # lunes-viernes
            acum += 1
        dc[f] = acum
    return dc


# ---------------------------------------------------------------------------
# Escenario 3: Cálculo de SLA — simula repetidas/dc_excel
# Para N registros: calcula si se resolvió en plazo según SLA por tipo,
# acumula estadísticas de tiempos de resolución.
# ---------------------------------------------------------------------------

SLA_DIAS = {1: 1, 2: 3, 3: 7, 4: 15, 5: 30}


def escenario3_actual(registros: list) -> dict:
    """Calcula SLA en formato ERP actual."""
    stats = {'en_plazo': 0, 'fuera_plazo': 0, 'total_dias': 0, 'max_dias': 0}
    for f_ini, f_fin, minutos, valoracion in registros:
        tipo = int(valoracion)
        sla = SLA_DIAS.get(tipo, 7)
        vencimiento_sla = Sm_Fecha_actual(f_ini, sla)
        dias = Df_Fechas_actual(f_fin, f_ini)
        stats['total_dias'] += dias
        if dias > stats['max_dias']:
            stats['max_dias'] = dias
        if f_fin <= vencimiento_sla:
            stats['en_plazo'] += 1
        else:
            stats['fuera_plazo'] += 1
    return stats


def escenario3_date(registros: list) -> dict:
    """Calcula SLA con objetos date nativos."""
    stats = {'en_plazo': 0, 'fuera_plazo': 0, 'total_dias': 0, 'max_dias': 0}
    for f_ini, f_fin, minutos, valoracion in registros:
        tipo = int(valoracion)
        sla = SLA_DIAS.get(tipo, 7)
        vencimiento_sla = Sm_Fecha_date(f_ini, sla)
        dias = Df_Fechas_date(f_fin, f_ini)
        stats['total_dias'] += dias
        if dias > stats['max_dias']:
            stats['max_dias'] = dias
        if f_fin <= vencimiento_sla:
            stats['en_plazo'] += 1
        else:
            stats['fuera_plazo'] += 1
    return stats


def escenario3_nuevo(registros: list) -> dict:
    """Calcula SLA en formato ordinal propuesto."""
    stats = {'en_plazo': 0, 'fuera_plazo': 0, 'total_dias': 0, 'max_dias': 0}
    for f_ini, f_fin, minutos, valoracion in registros:
        tipo = int(valoracion)
        sla = SLA_DIAS.get(tipo, 7)
        vencimiento_sla = Sm_Fecha_nuevo(f_ini, sla)
        dias = Df_Fechas_nuevo(f_fin, f_ini)
        stats['total_dias'] += dias
        if dias > stats['max_dias']:
            stats['max_dias'] = dias
        if f_fin <= vencimiento_sla:
            stats['en_plazo'] += 1
        else:
            stats['fuera_plazo'] += 1
    return stats


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

N_REGISTROS   = 50000    # registros reales por departamento/año
N_ITER        = 10   # iteraciones para promediar throughput
N_DEPARTS     = 1     # HOTLINE, SAT, SERVICIOS, OFLLP, FORMACIONES
ANCHO_COL     = 11


def _fmt(seg: float) -> str:
    if seg < 0.001:
        return f'{seg * 1_000_000:.1f} µs'
    if seg < 1:
        return f'{seg * 1_000:.2f} ms'
    return f'{seg:.3f} s'


def _speedup(t_actual: float, t_nuevo: float) -> str:
    if t_nuevo == 0:
        return '∞'
    ratio = t_actual / t_nuevo
    return f'{ratio:.1f}x'


def run():
    W = ANCHO_COL
    SEP3 = '-' * (22 + W * 4 + 3)
    SEP4 = '-' * (28 + W * 4 + 3)

    print('=' * (22 + W * 4 + 3))
    print(f'BENCHMARK FECHAS ERP — {N_REGISTROS} registros, {N_ITER} iteraciones')
    print('=' * (22 + W * 4 + 3))

    # -- preparar datos fuera del benchmark --
    regs_actual = _generar_registros_actual(N_REGISTROS)
    regs_nuevo  = _generar_registros_nuevo(N_REGISTROS)
    regs_date   = _generar_registros_date(N_REGISTROS)

    hoy_actual = Fecha_aNum(date.today().strftime('%d%m%Y'))
    hoy_nuevo  = date.today().toordinal()
    hoy_date   = date.today()

    ini_actual = Fecha_aNum('01012024')
    fin_actual = Fecha_aNum('31122024')
    ini_nuevo  = date(2024, 1, 1).toordinal()
    fin_nuevo  = date(2024, 12, 31).toordinal()
    ini_date   = date(2024, 1, 1)
    fin_date   = date(2024, 12, 31)

    resultados = []

    escenarios = [
        (
            'Esc.1 triple bucle',
            lambda: escenario1_actual(regs_actual, hoy_actual),
            lambda: escenario1_nuevo(regs_nuevo, hoy_nuevo),
            lambda: escenario1_date(regs_date, hoy_date),
        ),
        (
            'Esc.2 iter dia/dia',
            lambda: escenario2_actual(ini_actual, fin_actual),
            lambda: escenario2_nuevo(ini_nuevo, fin_nuevo),
            lambda: escenario2_date(ini_date, fin_date),
        ),
        (
            'Esc.3 SLA',
            lambda: escenario3_actual(regs_actual),
            lambda: escenario3_nuevo(regs_nuevo),
            lambda: escenario3_date(regs_date),
        ),
        (
            'Df_Fechas x10k',
            lambda: [Df_Fechas_actual(regs_actual[i % N_REGISTROS][1], regs_actual[i % N_REGISTROS][0]) for i in range(10_000)],
            lambda: [Df_Fechas_nuevo(regs_nuevo[i % N_REGISTROS][1], regs_nuevo[i % N_REGISTROS][0]) for i in range(10_000)],
            lambda: [Df_Fechas_date(regs_date[i % N_REGISTROS][1], regs_date[i % N_REGISTROS][0]) for i in range(10_000)],
        ),
        (
            'Sm_Fecha x10k',
            lambda: [Sm_Fecha_actual(regs_actual[i % N_REGISTROS][0], i % 365) for i in range(10_000)],
            lambda: [Sm_Fecha_nuevo(regs_nuevo[i % N_REGISTROS][0], i % 365) for i in range(10_000)],
            lambda: [Sm_Fecha_date(regs_date[i % N_REGISTROS][0], i % 365) for i in range(10_000)],
        ),
    ]

    # --- throughput ---
    print(f'\n--- THROUGHPUT (promedio por llamada, {N_ITER} iter) ---')
    print(f'\n{"Escenario":<22} {"Actual":>{W}} {"Ordinal":>{W}} {"date":>{W}} {"vs actual":>{W}}')
    print(SEP3)

    for nombre, fn_a, fn_n, fn_d in escenarios:
        t_a = timeit.timeit(fn_a, number=N_ITER) / N_ITER
        t_n = timeit.timeit(fn_n, number=N_ITER) / N_ITER
        t_d = timeit.timeit(fn_d, number=N_ITER) / N_ITER
        resultados.append((nombre, t_a, t_n, t_d))
        print(f'{nombre:<22} {_fmt(t_a):>{W}} {_fmt(t_n):>{W}} {_fmt(t_d):>{W}} {_speedup(t_a, min(t_n, t_d)):>{W}}')

    print(SEP3)
    tot_a = sum(t for _, t, _, _ in resultados)
    tot_n = sum(t for _, _, t, _ in resultados)
    tot_d = sum(t for _, _, _, t in resultados)
    print(f'{"TOTAL":<22} {_fmt(tot_a):>{W}} {_fmt(tot_n):>{W}} {_fmt(tot_d):>{W}} {_speedup(tot_a, min(tot_n, tot_d)):>{W}}')

    # --- ejecucion real ---
    print(f'\n--- EJECUCION REAL (1 pasada x {N_DEPARTS} departamentos, cada 3h) ---')
    print(f'\n{"Operacion":<28} {"Actual":>{W}} {"Ordinal":>{W}} {"date":>{W}} {"vs actual":>{W}}')
    print(SEP4)

    ops_reales = [
        ('Bucle registros',
            escenario1_actual, regs_actual, hoy_actual,
            escenario1_nuevo,  regs_nuevo,  hoy_nuevo,
            escenario1_date,   regs_date,   hoy_date),
        ('Iter dia/dia',
            escenario2_actual, ini_actual, fin_actual,
            escenario2_nuevo,  ini_nuevo,  fin_nuevo,
            escenario2_date,   ini_date,   fin_date),
        ('SLA',
            escenario3_actual, regs_actual, None,
            escenario3_nuevo,  regs_nuevo,  None,
            escenario3_date,   regs_date,   None),
    ]

    tot_ra = tot_rn = tot_rd = 0.0

    for fila in ops_reales:
        nombre = fila[0]
        fn_a, a1_a, a2_a = fila[1], fila[2], fila[3]
        fn_n, a1_n, a2_n = fila[4], fila[5], fila[6]
        fn_d, a1_d, a2_d = fila[7], fila[8], fila[9]

        if a2_a is None:
            t_a = timeit.timeit(lambda f=fn_a, a=a1_a: [f(a) for _ in range(N_DEPARTS)], number=10) / 10
            t_n = timeit.timeit(lambda f=fn_n, a=a1_n: [f(a) for _ in range(N_DEPARTS)], number=10) / 10
            t_d = timeit.timeit(lambda f=fn_d, a=a1_d: [f(a) for _ in range(N_DEPARTS)], number=10) / 10
        else:
            t_a = timeit.timeit(lambda f=fn_a, a=a1_a, b=a2_a: [f(a, b) for _ in range(N_DEPARTS)], number=10) / 10
            t_n = timeit.timeit(lambda f=fn_n, a=a1_n, b=a2_n: [f(a, b) for _ in range(N_DEPARTS)], number=10) / 10
            t_d = timeit.timeit(lambda f=fn_d, a=a1_d, b=a2_d: [f(a, b) for _ in range(N_DEPARTS)], number=10) / 10

        tot_ra += t_a
        tot_rn += t_n
        tot_rd += t_d
        print(f'{nombre:<28} {_fmt(t_a):>{W}} {_fmt(t_n):>{W}} {_fmt(t_d):>{W}} {_speedup(t_a, min(t_n, t_d)):>{W}}')

    print(SEP4)
    print(f'{"TOTAL 1 pasada":<28} {_fmt(tot_ra):>{W}} {_fmt(tot_rn):>{W}} {_fmt(tot_rd):>{W}} {_speedup(tot_ra, min(tot_rn, tot_rd)):>{W}}')
    print()
    print(f'Pasadas en 3h (actual):  {int(3*3600 / tot_ra):,}')
    print(f'Pasadas en 3h (ordinal): {int(3*3600 / tot_rn):,}')
    print(f'Pasadas en 3h (date):    {int(3*3600 / tot_rd):,}')
    print()
    print('vs actual: speedup del mejor entre ordinal y date.')


if __name__ == '__main__':
    run()
