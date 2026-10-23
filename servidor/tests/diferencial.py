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
