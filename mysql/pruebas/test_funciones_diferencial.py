"""Cada función portada, contra su original en PostgreSQL.

Son las funciones de las que sale el saldo de vacaciones de 351 personas.
Un día de diferencia en un borde de mes no es un detalle: es alguien a quien
el sistema nuevo le dice un número distinto del que le decía el viejo, y
nadie sabría cuál de los dos está bien.

Por eso no se prueba con un par de ejemplos. Se ejecuta el MISMO cálculo en
las dos bases sobre miles de casos —todos los días de varios años, con sus
29 de febrero y sus fines de mes— y se exige el mismo resultado, caso por
caso. Antes de comparar se copian a MySQL los feriados y los parámetros de
PostgreSQL: si hay una diferencia, que sea del cálculo y no de los datos.

Necesita la base PostgreSQL de referencia. Sin ella, estas pruebas se
saltan (y lo dicen): no se dan por buenas.
"""
from __future__ import annotations

import datetime as dt
import os
import re

import pytest

psycopg = pytest.importorskip("psycopg")

PG_URL = os.environ.get(
    "PG_REFERENCIA_URL", "postgresql://postgres@/rrhh_v4?host=/var/lib/pgtest&port=55432")


@pytest.fixture(scope="module")
def pg():
    try:
        con = psycopg.connect(PG_URL, autocommit=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Sin la base PostgreSQL de referencia ({exc}); no se puede comparar")
    yield con
    con.close()


@pytest.fixture(scope="module")
def my(base_de_pruebas, pg):
    """MySQL con los mismos feriados y parámetros que la referencia."""
    import migrar
    con = migrar.conectar(base_de_pruebas)
    cur = con.cursor()
    cur.execute("DELETE FROM feriados")
    feriados = pg.execute("select fecha, nombre, activo from public.feriados").fetchall()
    cur.executemany("INSERT INTO feriados (fecha, nombre, activo) VALUES (%s, %s, %s)",
                    [(f, n, 1 if a else 0) for f, n, a in feriados])
    for clave, valor in pg.execute("select clave, valor from public.app_config").fetchall():
        cur.execute("UPDATE app_config SET valor = %s WHERE clave = %s", (valor, clave))
    yield cur
    con.close()


def _dias(desde: dt.date, hasta: dt.date):
    d = desde
    while d <= hasta:
        yield d
        d += dt.timedelta(days=1)


def _en_mysql(cur, tabla_valores: list[tuple], columnas: str, expresion: str) -> list:
    """Evalúa `expresion` en MySQL para cada fila, en una sola consulta."""
    cur.execute("DROP TEMPORARY TABLE IF EXISTS casos")
    cur.execute(f"CREATE TEMPORARY TABLE casos (n INT PRIMARY KEY, {columnas})")
    # Las comas dentro de un tipo —DECIMAL(6,2)— no separan columnas.
    nombres = [c.split()[0] for c in re.split(r",\s*(?![^()]*\))", columnas)]
    marcas = ", ".join(["%s"] * (len(nombres) + 1))
    cur.executemany(f"INSERT INTO casos (n, {', '.join(nombres)}) VALUES ({marcas})",
                    [(i, *fila) for i, fila in enumerate(tabla_valores)])
    cur.execute(f"SELECT {expresion} FROM casos ORDER BY n")
    return [r[0] for r in cur.fetchall()]


def _diferencias(casos, en_pg, en_my, maximo=8) -> list[str]:
    malas = [f"{c}: PostgreSQL={a} MySQL={b}"
             for c, a, b in zip(casos, en_pg, en_my) if a != b]
    return malas[:maximo] + ([f"... y {len(malas) - maximo} más"] if len(malas) > maximo else [])


# ------------------------------------------------------------ antigüedad
CORTES = [dt.date(2024, 2, 28), dt.date(2024, 2, 29), dt.date(2024, 3, 1),
          dt.date(2025, 2, 28), dt.date(2025, 3, 1), dt.date(2025, 12, 31),
          dt.date(2026, 1, 1), dt.date(2026, 1, 31), dt.date(2026, 2, 28),
          dt.date(2026, 3, 31), dt.date(2026, 10, 23)]


def test_anios_cumplidos_igual_en_las_dos_bases(pg, my):
    """Todos los ingresos de 2015 a 2026 contra once fechas de corte, con
    29 de febrero y fines de mes entre ellas: 48.000 casos."""
    casos = [(ing, corte) for corte in CORTES
             for ing in _dias(dt.date(2015, 1, 1), dt.date(2026, 10, 23))]
    en_pg = [r[0] for r in pg.execute(
        """select public.anios_cumplidos(i, c)
             from unnest(%s::date[], %s::date[]) with ordinality as x(i, c, n) order by n""",
        ([i for i, _ in casos], [c for _, c in casos])).fetchall()]
    en_my = _en_mysql(my, casos, "ingreso DATE, corte DATE", "anios_cumplidos_al(ingreso, corte)")
    assert len(casos) > 40000
    assert _diferencias(casos, en_pg, en_my) == []


def test_anios_cumplidos_a_hoy_igual(pg, my):
    """La versión de un argumento, que es la que usan las consultas."""
    casos = [(ing,) for ing in _dias(dt.date(2000, 1, 1), dt.date(2026, 10, 23))]
    en_pg = [r[0] for r in pg.execute(
        """select public.anios_cumplidos(i)
             from unnest(%s::date[]) with ordinality as x(i, n) order by n""",
        ([c[0] for c in casos],)).fetchall()]
    en_my = _en_mysql(my, casos, "ingreso DATE", "anios_cumplidos(ingreso)")
    assert _diferencias(casos, en_pg, en_my) == []


def test_dias_por_antiguedad_igual(pg, my):
    casos = [(n,) for n in range(-2, 45)]
    en_pg = [r[0] for r in pg.execute(
        "select public.dias_por_antiguedad(n) from unnest(%s::int[]) with ordinality as x(n, o) order by o",
        ([c[0] for c in casos],)).fetchall()]
    en_my = _en_mysql(my, casos, "anios INT", "dias_por_antiguedad(anios)")
    assert _diferencias(casos, en_pg, en_my) == []


# ------------------------------------------------------- lo devengado
def test_lo_devengado_en_curso_igual_hoy(pg, my):
    """El saldo del año en curso: todos los ingresos de diez años, períodos
    1 a 30. Es la cifra que cada persona ve como «días del año en marcha»."""
    casos = [(ing, per) for per in (1, 2, 3, 5, 6, 7, 10, 15, 20, 30)
             for ing in _dias(dt.date(2016, 1, 1), dt.date(2026, 10, 23))]
    en_pg = [r[0] for r in pg.execute(
        """select public.dias_devengados_en_curso(i, p)
             from unnest(%s::date[], %s::int[]) with ordinality as x(i, p, n) order by n""",
        ([i for i, _ in casos], [p for _, p in casos])).fetchall()]
    en_my = _en_mysql(my, casos, "ingreso DATE, periodo INT", "dias_devengados_en_curso(ingreso, periodo)")
    assert _diferencias(casos, en_pg, en_my) == []


def test_lo_devengado_igual_en_otras_fechas_de_corte(pg, my):
    """Lo mismo contra once fechas de corte, para cubrir bordes de mes que
    hoy no se dan. En PostgreSQL la función solo mira hoy; se evalúa su
    misma expresión con la fecha de corte en lugar de current_date."""
    casos = [(ing, per, corte) for corte in CORTES for per in (1, 3, 6, 9)
             for ing in _dias(dt.date(2016, 1, 1), dt.date(2026, 10, 23), )
             if ing.day in (1, 15, 28, 29, 30, 31)]
    en_pg = [r[0] for r in pg.execute(
        """select round(
                 case when public.cfg_bool('vacaciones_extra_prorrateado')
                      then public.dias_por_antiguedad(p)
                      else public.cfg_int('vacaciones_dias_base')::numeric end *
                 least(greatest(
                   (extract(year  from age(c, (i + make_interval(years => p - 1))::date)) * 12
                  + extract(month from age(c, (i + make_interval(years => p - 1))::date))), 0), 12)
                 / 12.0, 2)::numeric
             from unnest(%s::date[], %s::int[], %s::date[]) with ordinality as x(i, p, c, n)
            order by n""",
        ([a for a, _, _ in casos], [b for _, b, _ in casos], [c for _, _, c in casos])).fetchall()]
    en_my = _en_mysql(my, casos, "ingreso DATE, periodo INT, corte DATE",
                      "dias_devengados_al(ingreso, periodo, corte)")
    assert len(casos) > 5000
    assert _diferencias(casos, en_pg, en_my) == []


# ------------------------------------------------------------ calendario
def _rangos():
    """Cada día de 2026 como inicio, con duraciones de 0 a 20 días."""
    return [(ini, ini + dt.timedelta(days=largo))
            for ini in _dias(dt.date(2026, 1, 1), dt.date(2026, 12, 31))
            for largo in range(0, 21, 2)]


@pytest.mark.parametrize("funcion", ["dias_habiles", "fines_de_semana_completos"])
def test_conteos_de_calendario_iguales(pg, my, funcion):
    casos = _rangos()
    en_pg = [r[0] for r in pg.execute(
        f"""select public.{funcion}(a, b)
              from unnest(%s::date[], %s::date[]) with ordinality as x(a, b, n) order by n""",
        ([a for a, _ in casos], [b for _, b in casos])).fetchall()]
    en_my = _en_mysql(my, casos, "inicio DATE, fin DATE", f"{funcion}(inicio, fin)")
    assert _diferencias(casos, en_pg, en_my) == []


@pytest.mark.parametrize("tipo", ["vacacion", "permiso"])
def test_calcular_dias_igual(pg, my, tipo):
    """Lo que descuenta una solicitud. Vacaciones en días calendario menos
    feriados; permisos en días hábiles."""
    casos = _rangos() + [(dt.date(2026, 3, 10), dt.date(2026, 3, 1))]   # fin antes del inicio
    en_pg = [r[0] for r in pg.execute(
        """select public.calcular_dias(%s::request_type, a, b)
             from unnest(%s::date[], %s::date[]) with ordinality as x(a, b, n) order by n""",
        (tipo, [a for a, _ in casos], [b for _, b in casos])).fetchall()]
    en_my = _en_mysql(my, casos, "inicio DATE, fin DATE", f"calcular_dias('{tipo}', inicio, fin)")
    assert _diferencias(casos, en_pg, en_my) == []


def test_situacion_de_los_fines_de_semana_igual(pg, my):
    from decimal import Decimal
    casos = [(d, Decimal(a), Decimal(c)) for d in (True, False) for a in ("0", "15", "16")
             for c in ("0", "1", "7.5", "15", "16", "20")]
    en_pg = [r[0] for r in pg.execute(
        """select public.situacion_fines_semana(d, a, c)
             from unnest(%s::bool[], %s::numeric[], %s::numeric[]) with ordinality as x(d, a, c, n)
            order by n""",
        ([x[0] for x in casos], [x[1] for x in casos], [x[2] for x in casos])).fetchall()]
    en_my = _en_mysql(my, [(1 if d else 0, a, c) for d, a, c in casos],
                      "dev BOOLEAN, asig DECIMAL(6,2), cons DECIMAL(6,2)",
                      "situacion_fines_semana(dev, asig, cons)")
    assert _diferencias(casos, en_pg, en_my) == []
