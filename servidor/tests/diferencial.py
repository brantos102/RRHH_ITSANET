"""Herramientas para comparar una regla de Python con su original de PostgreSQL.

Las reglas que pasaron de PL/pgSQL a Python se prueban así: la misma persona
con los mismos datos en las dos bases, la función original en PostgreSQL y la
nueva en MySQL, y se exige que dejen las tablas igual.

  PostgreSQL   la base de referencia (PG_REFERENCIA_URL), dentro de una
               transacción que se deshace al terminar: queda como estaba.
  MySQL        la base de pruebas del servidor. Lo que se crea se borra al
               terminar, incluida la bitácora (con la retención autorizada,
               en la misma conexión, y desactivada antes de soltarla).

Si la base de referencia no está, las pruebas se omiten con el motivo: sin
ella no hay contra qué comparar, y una prueba diferencial que pasa sin
comparar nada sería peor que ninguna.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app import db

PG_URL = os.environ.get(
    "PG_REFERENCIA_URL", "postgresql://postgres@/rrhh_v4?host=/var/lib/pgtest&port=55432")


def conectar_pg():
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row
    try:
        return psycopg.connect(PG_URL, row_factory=dict_row)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Sin la base PostgreSQL de referencia ({exc}); no se puede comparar")


def normal(valor: Any) -> Any:
    """Un valor comparable entre las dos bases: 15 y 15.00 son lo mismo."""
    if isinstance(valor, bool) or valor is None:
        return valor
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor)).normalize()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    return valor


def normal_fila(fila: dict | None, columnas: list[str]) -> tuple | None:
    if fila is None:
        return None
    return tuple(normal(bool(fila[c]) if c in _BOOLEANAS and fila[c] is not None else fila[c])
                 for c in columnas)


_BOOLEANAS = {"devengado", "caducado", "activo", "es_adelanto"}


class Dos:
    """Las dos bases a la vez: lo que se crea aquí se crea igual en ambas."""

    def __init__(self, pg):
        self.pg = pg
        self.personas: list[str] = []
        self._config_original: dict[str, str | None] = {}

    # ------------------------------------------------------- configuración
    async def misma_configuracion(self, **cambios: str) -> None:
        """MySQL con los parámetros de PostgreSQL, y los cambios en las dos."""
        filas = self.pg.execute("select clave, valor from public.app_config").fetchall()
        en_pg = {f["clave"]: f["valor"] for f in filas}
        en_pg.update(cambios)
        for clave, valor in cambios.items():
            self.pg.execute("update public.app_config set valor = %s where clave = %s", (valor, clave))
        for clave, valor in en_pg.items():
            antes = await db.obtener_uno("SELECT valor FROM app_config WHERE clave = %s", (clave,))
            if clave not in self._config_original:
                self._config_original[clave] = antes["valor"] if antes else None
            if antes is not None and antes["valor"] != valor:
                await db.ejecutar("UPDATE app_config SET valor = %s WHERE clave = %s", (valor, clave))

    async def mismos_feriados(self) -> None:
        filas = self.pg.execute("select fecha, nombre, activo from public.feriados").fetchall()
        for f in filas:
            await db.ejecutar(
                """INSERT INTO feriados (fecha, nombre, activo) VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), activo = VALUES(activo)""",
                (f["fecha"], f["nombre"], f["activo"]))

    # ------------------------------------------------------------ personas
    async def persona(self, cedula: str, fecha_ingreso, rol: str = "empleado",
                      nombre: str = "Persona Diferencial", **extra) -> str:
        pid = str(uuid.uuid4())
        campos = {"id": pid, "cedula": cedula, "nombre": nombre, "email": f"{cedula}@dif.test",
                  "rol": rol, "fecha_ingreso": fecha_ingreso, **extra}
        cols = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        self.pg.execute(f"insert into public.users ({cols}) values ({marcas})", tuple(campos.values()))
        await db.ejecutar(f"INSERT INTO users ({cols}) VALUES ({marcas})", tuple(campos.values()))
        self.personas.append(pid)
        return pid

    async def periodo(self, user_id: str, **campos) -> None:
        cols = ", ".join(["user_id", *campos])
        marcas = ", ".join(["%s"] * (len(campos) + 1))
        valores = (user_id, *campos.values())
        self.pg.execute(f"insert into public.vacation_periods ({cols}) values ({marcas})", valores)
        await db.ejecutar(f"INSERT INTO vacation_periods ({cols}) VALUES ({marcas})", valores)

    # ------------------------------------------------------------- lectura
    PERIODO = ["periodo", "fecha_desde", "fecha_hasta", "dias_asignados", "dias_consumidos",
               "devengado", "vence_en", "caducado", "fines_semana_obligatorios",
               "fines_semana_consumidos"]

    async def foto(self, user_id: str) -> tuple[dict, dict]:
        """Lo que una regla de períodos puede cambiar, en las dos bases."""
        cols = ", ".join(self.PERIODO)

        def de_pg():
            return {
                "periodos": [normal_fila(f, self.PERIODO) for f in self.pg.execute(
                    f"select {cols} from public.vacation_periods where user_id = %s order by periodo",
                    (user_id,)).fetchall()],
                "saldo": normal(self.pg.execute(
                    "select dias_vacaciones from public.users where id = %s",
                    (user_id,)).fetchone()["dias_vacaciones"]),
                "movimientos": [normal_fila(f, ["dias", "saldo_previo", "saldo_nuevo", "motivo"])
                                for f in self.pg.execute(
                    """select dias, saldo_previo, saldo_nuevo, motivo from public.vacation_movements
                        where user_id = %s order by created_at, motivo""", (user_id,)).fetchall()],
            }

        async def de_my():
            return {
                "periodos": [normal_fila(f, self.PERIODO) for f in await db.obtener_todos(
                    f"SELECT {cols} FROM vacation_periods WHERE user_id = %s ORDER BY periodo",
                    (user_id,))],
                "saldo": normal((await db.obtener_uno(
                    "SELECT dias_vacaciones FROM users WHERE id = %s", (user_id,)))["dias_vacaciones"]),
                "movimientos": [normal_fila(f, ["dias", "saldo_previo", "saldo_nuevo", "motivo"])
                                for f in await db.obtener_todos(
                    """SELECT dias, saldo_previo, saldo_nuevo, motivo FROM vacation_movements
                        WHERE user_id = %s ORDER BY created_at, motivo""", (user_id,))],
            }

        return de_pg(), await de_my()

    def pg_llamar(self, sql: str, params=()) -> tuple[Any, str | None]:
        """Ejecuta en PostgreSQL; devuelve (resultado, mensaje de error)."""
        self.pg.execute("savepoint antes")
        try:
            fila = self.pg.execute(sql, params).fetchone()
            self.pg.execute("release savepoint antes")
            return (next(iter(fila.values())) if fila else None), None
        except Exception as exc:  # noqa: BLE001
            self.pg.execute("rollback to savepoint antes")
            diag = getattr(exc, "diag", None)
            return None, (diag.message_primary if diag else str(exc))

    # ------------------------------------------------------------ limpieza
    async def limpiar(self) -> None:
        self.pg.rollback()
        self.pg.close()
        if self.personas:
            async with db.transaccion():
                ids = db.lista(self.personas)
                await db.ejecutar("SET @retencion = 'autorizada'")
                try:
                    await db.ejecutar("DELETE FROM audit_logs WHERE user_id IN %s", (ids,))
                    for tabla in ("notifications", "vacation_movements", "vacation_periods"):
                        await db.ejecutar(f"DELETE FROM {tabla} WHERE user_id IN %s", (ids,))
                    await db.ejecutar("DELETE FROM users WHERE id IN %s", (ids,))
                finally:
                    await db.ejecutar("SET @retencion = NULL")
        for clave, valor in self._config_original.items():
            if valor is not None:
                await db.ejecutar("UPDATE app_config SET valor = %s WHERE clave = %s", (valor, clave))


@pytest.fixture
async def dos():
    d = Dos(conectar_pg())
    try:
        yield d
    finally:
        await d.limpiar()


def cedula_de_prueba(n: int) -> str:
    """Una cédula válida (Pichincha, tercer dígito 5) que no es de nadie real
    del sistema: las de prueba empiezan por 17599."""
    base = f"17599{n:04d}"
    suma = 0
    for i, d in enumerate(base):
        p = int(d) * (2 if i % 2 == 0 else 1)
        suma += p - 9 if p > 9 else p
    return base + str((10 - suma % 10) % 10)


# ----------------------------------------------------------- la muestra
# Una base con ~70 personas inventadas y solicitudes en todos los estados
# (mysql/pruebas/muestra_pg.py), en PostgreSQL y trasladada a MySQL con el
# guion del corte. Con ella una regla se compara para TODA la muestra, no
# para un caso armado a mano.
PG_ADMIN = os.environ.get("PG_ADMIN_URL", "postgresql://postgres@/postgres?host=/var/lib/pgtest&port=55432")
PG_PLANTILLA = os.environ.get("PG_PLANTILLA", "rrhh_v4")
MUESTRA = "rrhh_muestra"
MUESTRA_MY = "rrhh_prueba_muestra"


def json_normal(valor: Any) -> Any:
    """Lo que llegaría al navegador: el JSON que FastAPI arma de un dict de
    Python, o el que PostgreSQL arma con jsonb. Así se comparan los dos."""
    import datetime as dt
    import json

    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, (dt.date, dt.datetime, dt.time)):
            return v.isoformat()
        if isinstance(v, uuid.UUID):
            return str(v)
        raise TypeError(type(v))
    return _instantes(json.loads(json.dumps(valor, default=conv)))


def _instantes(valor: Any) -> Any:
    """Una fecha-hora escrita en JSON, como instante: «…56.5388+00:00» de
    PostgreSQL y «…51.538800-05:00» de Python son el mismo momento."""
    import datetime as dt
    import re
    if isinstance(valor, dict):
        return {k: _instantes(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_instantes(v) for v in valor]
    if isinstance(valor, str) and re.match(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d", valor):
        try:
            return dt.datetime.fromisoformat(valor)
        except ValueError:
            return valor
    return valor


from contextlib import asynccontextmanager  # noqa: E402


class _Deshacer(Exception):
    pass


@asynccontextmanager
async def y_deshacer():
    """Lo de adentro corre en MySQL dentro de una transacción que se deshace
    al salir: la muestra queda como estaba para la siguiente prueba."""
    try:
        async with db.transaccion():
            yield
            raise _Deshacer
    except _Deshacer:
        pass


@pytest.fixture(scope="module")
def muestra():
    """(conexión a la muestra de PostgreSQL, nombre de la base MySQL).

    Mientras dura el módulo, la aplicación apunta a la muestra de MySQL.
    """
    import sys
    from pathlib import Path
    from urllib.parse import urlparse

    import pymysql
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mysql" / "pruebas"))
    import muestra_pg
    import trasladar
    from app.config import get_settings

    psycopg = pytest.importorskip("psycopg")
    try:
        muestra_pg.crear(PG_ADMIN, PG_PLANTILLA, MUESTRA)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Sin PostgreSQL de referencia para armar la muestra ({exc})")
    pg_url = PG_ADMIN.replace("/postgres?", f"/{MUESTRA}?")
    muestra_pg.llenar(pg_url)

    ajustes = get_settings()
    original = ajustes.mysql_url
    u = urlparse(original)
    url = original.replace(u.path, f"/{MUESTRA_MY}", 1)
    raiz = pymysql.connect(unix_socket=None if u.hostname not in (None, "localhost") else
                           dict(p.split("=") for p in u.query.split("&") if p).get("unix_socket"),
                           host=u.hostname or "localhost", user=u.username or "root",
                           password=u.password or "", charset="utf8mb4", autocommit=True)
    raiz.cursor().execute(f"DROP DATABASE IF EXISTS `{MUESTRA_MY}`")
    raiz.cursor().execute(f"CREATE DATABASE `{MUESTRA_MY}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    import migrar
    assert migrar.principal(aplicar=True, url=url) == 0
    assert trasladar.principal(pg_url, aplicar=True, destino=url) == 0

    pg = psycopg.connect(pg_url)
    from psycopg.rows import dict_row
    pg.row_factory = dict_row
    pg.execute("set time zone 'America/Guayaquil'")
    pg.commit()
    ajustes.mysql_url = url
    try:
        yield pg
    finally:
        ajustes.mysql_url = original
        pg.close()
        raiz.cursor().execute(f"DROP DATABASE IF EXISTS `{MUESTRA_MY}`")
        raiz.close()
