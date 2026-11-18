"""Las vistas de MySQL contra las de PostgreSQL, fila por fila.

Una base de muestra con personas inventadas (muestra_pg.py) se llena en
PostgreSQL con las funciones originales, se traslada a MySQL con el mismo
guion que se usará el día del corte (trasladar.py) y después se consulta
cada vista en las dos bases. Tienen que dar las mismas filas con los mismos
valores.

De paso, esto es un ensayo completo del traslado sobre datos con variedad:
solicitudes en todos los estados, históricos, bajas, garita, temporales,
mensajes, documentos firmados.
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import uuid

import pymysql
import pytest

import muestra_pg
import trasladar

psycopg = pytest.importorskip("psycopg")

PG_ADMIN = os.environ.get("PG_ADMIN_URL", "postgresql://postgres@/postgres?host=/var/lib/pgtest&port=55432")
PG_PLANTILLA = os.environ.get("PG_PLANTILLA", "rrhh_v4")
PG_MUESTRA = "rrhh_muestra"

# Columnas que dependen del instante en que se consulta: se comparan con
# tolerancia, porque las dos consultas no corren en el mismo microsegundo.
CON_TOLERANCIA = {
    ("v_garita_hoy", "minutos_de_atraso"): decimal.Decimal(1),
    ("v_temporales_dentro", "horas_hasta_ahora"): decimal.Decimal("0.02"),
}

VISTAS = [
    "v_acumulacion_excesiva", "v_antiguedad_referencia", "v_caducidad", "v_calendario_equipo",
    "v_cambios_ficha_pendientes", "v_catalogo_permisos", "v_conversaciones_bandeja",
    "v_cuentas_de_prueba", "v_devengo_cotejo", "v_ficha_sin_confirmar", "v_fichas_incompletas",
    "v_fines_semana", "v_garita_hoy", "v_historial_vacaciones", "v_historico_resumen",
    "v_informe_solicitudes", "v_informes_firmados", "v_jefaturas", "v_jefaturas_admin",
    "v_jerarquia", "v_jornadas_detalle", "v_jornadas_sin_cerrar", "v_legal_colaborador",
    "v_lineamientos", "v_panel_configuracion", "v_pasivo_vacaciones", "v_resumen_general",
    "v_retornos", "v_rrhh_por_region", "v_saldos_desalineados", "v_salidas", "v_sin_correo",
    "v_sin_entrada", "v_talento_humano", "v_temporales_dentro", "v_trazabilidad_empleado",
    "v_trazabilidad_solicitudes",
]


def _pg_url(base: str) -> str:
    return PG_ADMIN.replace("/postgres?", f"/{base}?")


@pytest.fixture(scope="module")
def bases(base_de_pruebas):
    try:
        muestra_pg.crear(PG_ADMIN, PG_PLANTILLA, PG_MUESTRA)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Sin PostgreSQL de referencia para armar la muestra ({exc})")
    muestra_pg.llenar(_pg_url(PG_MUESTRA))
    # El mismo traslado del día del corte, sobre la base de pruebas recién migrada.
    assert trasladar.principal(_pg_url(PG_MUESTRA), aplicar=True, destino=base_de_pruebas) == 0
    pg = psycopg.connect(_pg_url(PG_MUESTRA))
    pg.execute("set time zone 'America/Guayaquil'")
    my = pymysql.connect(**_pymysql(base_de_pruebas))
    yield pg, my
    pg.close()
    my.close()


def _pymysql(url: str) -> dict:
    import conexion
    p = conexion.parametros(url)
    return {"host": p["host"], "port": p["port"], "user": p["user"], "password": p["password"],
            "database": p["db"], "charset": "utf8mb4", "unix_socket": p.get("unix_socket"),
            "init_command": p["init_command"], "autocommit": True}


def _arreglo_pg(texto: str) -> list[str]:
    """«{admin,rrhh}» -> ["admin", "rrhh"]: los arreglos de enumerados que
    psycopg no sabe leer."""
    cuerpo = texto.strip("{}")
    return [x.strip('"') for x in cuerpo.split(",")] if cuerpo else []


def _normal(valor, booleana: bool):
    if valor is None:
        return None
    if booleana:
        return bool(valor)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, dt.datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(dt.timezone(dt.timedelta(hours=-5))).replace(tzinfo=None)
        return valor
    if isinstance(valor, dt.timedelta):
        return (dt.datetime.min + valor).time()
    if isinstance(valor, (int, float, decimal.Decimal)):
        return decimal.Decimal(str(valor)).normalize()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, list):
        return json.dumps(valor, sort_keys=True)
    if isinstance(valor, str) and valor.startswith("[") and valor.endswith("]"):
        try:
            return json.dumps(json.loads(valor), sort_keys=True)
        except ValueError:
            return valor
    if isinstance(valor, str) and valor.startswith("{") and valor.endswith("}") and "\"" not in valor[:2]:
        return json.dumps(_arreglo_pg(valor), sort_keys=True)
    return valor


def _filas(cursor, sql: str) -> tuple[list[str], list[tuple]]:
    cursor.execute(sql)
    return [d[0] for d in cursor.description], cursor.fetchall()


@pytest.mark.parametrize("vista", VISTAS)
def test_la_vista_da_lo_mismo(bases, vista):
    pg, my = bases
    with pg.cursor() as c:
        cols_pg, filas_pg = _filas(c, f"select * from public.{vista}")
        booleanas = {d.name for d in c.description if d.type_code == 16}
    with my.cursor() as c:
        cols_my, filas_my = _filas(c, f"SELECT * FROM {vista}")
    assert cols_my == cols_pg, "mismas columnas, en el mismo orden"

    tolerantes = {i: tol for i, col in enumerate(cols_pg)
                  if (tol := CON_TOLERANCIA.get((vista, col))) is not None}

    def normalizar(filas):
        resultado = []
        for f in filas:
            resultado.append(tuple(
                None if i in tolerantes else _normal(v, cols_pg[i] in booleanas)
                for i, v in enumerate(f)))
        return sorted(resultado, key=lambda t: tuple((x is None, str(x)) for x in t))

    a, b = normalizar(filas_pg), normalizar(filas_my)
    assert len(b) == len(a)
    for fila_pg, fila_my in zip(a, b):
        if fila_pg != fila_my:
            distintas = {cols_pg[i]: (x, y) for i, (x, y) in enumerate(zip(fila_pg, fila_my)) if x != y}
            pytest.fail(f"{vista}: la fila difiere en {distintas}")

    for i, tol in tolerantes.items():
        valores_pg = sorted(_normal(f[i], False) or 0 for f in filas_pg)
        valores_my = sorted(_normal(f[i], False) or 0 for f in filas_my)
        assert all(abs(x - y) <= tol for x, y in zip(valores_pg, valores_my)), cols_pg[i]


def test_la_muestra_no_esta_vacia(bases):
    """Una comparación de vistas vacías pasa sin comparar nada."""
    pg, _ = bases
    for vista, minimo in [("v_calendario_equipo", 40), ("v_garita_hoy", 3), ("v_retornos", 2),
                          ("v_informes_firmados", 5), ("v_salidas", 2), ("v_temporales_dentro", 1),
                          ("v_conversaciones_bandeja", 3), ("v_cambios_ficha_pendientes", 1),
                          ("v_historial_vacaciones", 40), ("v_jornadas_sin_cerrar", 1)]:
        n = pg.execute(f"select count(*) from public.{vista}").fetchone()[0]
        assert n >= minimo, f"{vista} tiene {n} filas en la muestra"
