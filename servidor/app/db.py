"""Acceso a MySQL 8.0 con un pool asíncrono.

Misma interfaz que tenía la versión de PostgreSQL —`obtener_uno`,
`obtener_todos`, `ejecutar`— para que los routers cambien lo menos posible, y
una pieza nueva, `transaccion()`, que la versión de PostgreSQL no necesitaba.

POR QUÉ HACE FALTA `transaccion()`. En PostgreSQL buena parte de la lógica
vivía en funciones de la base, y una función se ejecuta entera dentro de una
transacción: `jefatura_quitar` movía a los colaboradores Y sus solicitudes
pendientes, o no movía nada. En MySQL esa lógica pasa a Python, que hace
varias consultas seguidas, y sin una transacción explícita un fallo a la
mitad dejaría a la gente reasignada y sus solicitudes no.

    async with transaccion():
        await ejecutar("update users ...")
        await ejecutar("update requests ...")   # va en la MISMA transacción

Dentro del bloque, los ayudantes de siempre se unen solos a la transacción
en curso: no hay que pasar la conexión de función en función. Fuera de un
bloque, cada consulta se confirma sola, como antes.

LO QUE SE CONVIERTE AL LEER, para que el resto del código no note el cambio
de motor y siga recibiendo lo que recibía de PostgreSQL:

  BOOLEAN y expresiones lógicas   bool. MySQL los da como 1/0. Se reconocen
                                  porque MySQL informa un tamaño de 1 para
                                  ellos y de 2 o más para cualquier número.
  JSON                            dict / list. MySQL los da como texto.
  CHAR(36) con forma de UUID      uuid.UUID, como el tipo uuid de PostgreSQL.
  DATETIME                        datetime CON la zona de Ecuador. MySQL los
                                  da sin zona; sin esto, la API mandaría
                                  fechas ambiguas al navegador.
  TIME                            time (hora del día). PyMySQL los da como
                                  una duración.

Cada conexión fija utf8mb4 y la hora de Ecuador. Las dos cosas se probaron
en esta migración: sin utf8mb4, «Suárez» se guarda corrompido sin dar
error; sin la zona, «hoy» empieza a las 19:00, que es el defecto que tenía
el sistema sobre Supabase.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import decimal
import json
import re
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiomysql
from pymysql.constants import FIELD_TYPE

from .config import get_settings

# Ecuador continental no tiene horario de verano desde 1993. Una zona fija por
# desplazamiento no depende de que el servidor tenga cargadas las tablas de
# zonas horarias de MySQL, que en una instalación nueva suelen faltar.
ZONA_ECUADOR = dt.timezone(dt.timedelta(hours=-5), "America/Guayaquil")
_ZONA_SQL = "-05:00"

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_pool: aiomysql.Pool | None = None
_pool_bucle: asyncio.AbstractEventLoop | None = None
_transaccion: ContextVar[aiomysql.Connection | None] = ContextVar("_transaccion", default=None)


# ------------------------------------------------------------- al escribir
# PyMySQL no sabe escribir un UUID, un dict ni una lista de JSON, y una fecha
# con zona la escribiría con la hora de su zona y no con la de Ecuador. Se
# convierten aquí, antes de enviar.
#
# Se hace convirtiendo los PARÁMETROS y no registrando codificadores en la
# conexión: aiomysql ignora los codificadores de la conexión y usa los
# globales de PyMySQL. Una primera versión de este archivo los asignaba a la
# conexión, y no tenía ningún efecto. Se detectó leyendo el código de
# aiomysql antes de dar el paso por bueno.
def _en_json(valor: Any) -> Any:
    """Lo que json no sabe escribir, como lo escribía jsonb de PostgreSQL.

    Un Decimal va como NÚMERO, no como texto: con `default=str` un saldo de
    15.25 quedaba guardado como "15.25", entre comillas, y quien lo leyera
    después recibía un texto donde esperaba un número.
    """
    if isinstance(valor, decimal.Decimal):
        return int(valor) if valor == valor.to_integral_value() and valor.as_tuple().exponent >= 0 \
            else float(valor)
    if isinstance(valor, (dt.date, dt.datetime, dt.time)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    return str(valor)


def a_json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, default=_en_json)


def _a_mysql(valor: Any) -> Any:
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, dict):
        return a_json(valor)
    if isinstance(valor, dt.datetime) and valor.tzinfo is not None:
        # Una fecha con zona —la de un token, la de datetime.now(timezone.utc)—
        # se guarda en hora de Ecuador. Guardarla tal cual escribiría la hora
        # de Londres en una columna que se lee como hora de Quito.
        return valor.astimezone(ZONA_ECUADOR).replace(tzinfo=None)
    if isinstance(valor, (list, tuple)):
        # Una tupla es el valor de un `IN %s`: se convierte elemento a
        # elemento y sigue siendo tupla. Una lista es un dato JSON.
        if isinstance(valor, tuple):
            return tuple(_a_mysql(v) for v in valor)
        return a_json(valor)
    return valor


# ---------------------------------------------------------------- al leer
def _convertir_fila(fila: dict[str, Any] | None, descripcion) -> dict[str, Any] | None:
    if fila is None or not descripcion:
        return fila
    for nombre, tipo, _, interno, *_ in descripcion:
        valor = fila.get(nombre)
        if valor is None:
            continue
        if tipo in (FIELD_TYPE.TINY, FIELD_TYPE.LONGLONG) and interno == 1:
            fila[nombre] = bool(valor)
        elif tipo == FIELD_TYPE.JSON:
            fila[nombre] = json.loads(valor) if isinstance(valor, (str, bytes)) else valor
        elif tipo in (FIELD_TYPE.STRING, FIELD_TYPE.VAR_STRING) and isinstance(valor, str) \
                and len(valor) == 36 and _UUID.match(valor):
            fila[nombre] = uuid.UUID(valor)
        elif isinstance(valor, dt.datetime) and valor.tzinfo is None:
            fila[nombre] = valor.replace(tzinfo=ZONA_ECUADOR)
        elif tipo == FIELD_TYPE.TIME and isinstance(valor, dt.timedelta) \
                and dt.timedelta(0) <= valor < dt.timedelta(days=1):
            # PyMySQL entrega TIME como duración; psycopg, como hora del día.
            # Sin esto, str() de las 9:00 da «9:00:00» y el «[:5]» con que
            # las pantallas recortan la hora mostraba «9:00:».
            fila[nombre] = (dt.datetime.min + valor).time()
    return fila


# --------------------------------------------------------------- conexión
def _parametros(url: str) -> dict:
    u = urlparse(url)
    if not u.scheme.startswith("mysql"):
        raise RuntimeError(
            f"MYSQL_URL tiene que empezar por mysql://, no por {u.scheme}://")
    consulta = parse_qs(u.query)
    p = {
        "host": u.hostname or "localhost",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "db": (u.path or "/").lstrip("/"),
        "charset": "utf8mb4",
        "init_command": (f"SET time_zone = '{_ZONA_SQL}', "
                         "NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci"),
        "autocommit": True,
        "cursorclass": aiomysql.DictCursor,
    }
    if "unix_socket" in consulta:
        p["unix_socket"] = consulta["unix_socket"][0]
    return p


async def abrir_pool() -> aiomysql.Pool:
    """El pool de conexiones, creado la primera vez que se pide.

    Un pool de aiomysql pertenece al bucle de eventos que lo creó y no sirve
    en otro. El servidor tiene un solo bucle, pero un guion que llama dos
    veces a asyncio.run —y las pruebas, que abren uno por prueba— no: si el
    bucle cambió, el pool viejo se abandona (sus conexiones murieron con su
    bucle) y se abre otro.
    """
    global _pool, _pool_bucle
    bucle = asyncio.get_running_loop()
    if _pool is not None and _pool_bucle is not bucle:
        # No se cierra: cerrarlo tocaría conexiones de otro bucle desde este.
        _pool = None
    if _pool is None:
        _pool_bucle = bucle
        settings = get_settings()
        _pool = await aiomysql.create_pool(
            minsize=1, maxsize=10,
            # Una conexión que lleva una hora quieta se renueva. MySQL corta
            # por su cuenta las conexiones inactivas (wait_timeout, 8 h por
            # omisión), y una conexión cortada que sigue en el pool falla en
            # la primera consulta de la mañana con «MySQL server has gone
            # away».
            pool_recycle=3600,
            **_parametros(settings.mysql_url),
        )
    return _pool


async def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


@asynccontextmanager
async def conexion():
    """Una conexión: la de la transacción en curso, o una del pool."""
    actual = _transaccion.get()
    if actual is not None:
        yield actual
        return
    pool = await abrir_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaccion():
    """Todo lo de adentro se confirma junto, o no se confirma nada.

    Anidable: un bloque dentro de otro se une a la transacción de afuera, de
    modo que una regla de negocio que abre la suya puede llamarse desde otra
    que ya tiene una abierta sin partirla en dos.
    """
    if _transaccion.get() is not None:
        yield _transaccion.get()
        return
    pool = await abrir_pool()
    async with pool.acquire() as conn:
        await conn.begin()
        marca = _transaccion.set(conn)
        try:
            yield conn
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise
        finally:
            _transaccion.reset(marca)


def en_transaccion() -> bool:
    return _transaccion.get() is not None


# ------------------------------------------------------------- ayudantes
def _argumentos(params: tuple | dict | list | None):
    """Siempre una tupla o un dict, nunca None, y cada valor ya convertido.

    PyMySQL solo aplica el formato `%` cuando hay parámetros. Pasar siempre
    algo hace que `%%` signifique `%` en todas las consultas, igual que con
    psycopg, que es como están escritas.
    """
    if params is None:
        return ()
    if isinstance(params, dict):
        return {k: _a_mysql(v) for k, v in params.items()}
    return tuple(_a_mysql(v) for v in params)


async def _ejecutar_en(conn, sql: str, params) -> aiomysql.DictCursor:
    cur = await conn.cursor()
    await cur.execute(sql, _argumentos(params))
    return cur


async def obtener_uno(sql: str, params: tuple | dict | list | None = ()) -> dict[str, Any] | None:
    async with conexion() as conn:
        cur = await _ejecutar_en(conn, sql, params)
        try:
            return _convertir_fila(await cur.fetchone(), cur.description)
        finally:
            await cur.close()


async def obtener_todos(sql: str, params: tuple | dict | list | None = ()) -> list[dict[str, Any]]:
    async with conexion() as conn:
        cur = await _ejecutar_en(conn, sql, params)
        try:
            filas = await cur.fetchall()
            return [_convertir_fila(f, cur.description) for f in filas]
        finally:
            await cur.close()


async def ejecutar(sql: str, params: tuple | dict | list | None = ()) -> int:
    """Una sentencia que no devuelve filas. Devuelve cuántas tocó."""
    async with conexion() as conn:
        cur = await _ejecutar_en(conn, sql, params)
        try:
            return cur.rowcount
        finally:
            await cur.close()


async def insertar(sql: str, params: tuple | dict | list | None = ()) -> int:
    """Un INSERT que devuelve el id AUTO_INCREMENT que generó.

    En PostgreSQL esto se resolvía con `returning id`. MySQL no tiene
    RETURNING; el último id generado por ESTA conexión está en lastrowid.
    """
    async with conexion() as conn:
        cur = await _ejecutar_en(conn, sql, params)
        try:
            return cur.lastrowid
        finally:
            await cur.close()


def para_json(valor: Any) -> Any:
    """Un resultado que antes armaba PostgreSQL como JSON, listo para la API.

    En PostgreSQL, explicar_saldo y compañía devolvían jsonb y los números
    llegaban al navegador como números. Ahora esas reglas viven en Python y
    sus números son Decimal, que FastAPI escribe como TEXTO ("18.00"): la
    pantalla que suma saldos recibiría cadenas. Esto los deja como números,
    igual que antes. Las fechas las sigue escribiendo FastAPI en ISO.
    """
    if isinstance(valor, decimal.Decimal):
        return int(valor) if valor == valor.to_integral_value() and valor.as_tuple().exponent >= 0 \
            else float(valor)
    if isinstance(valor, dict):
        return {k: para_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [para_json(v) for v in valor]
    return valor


def nuevo_id() -> uuid.UUID:
    """El id de una fila nueva, generado aquí y no en la base.

    En PostgreSQL la base lo generaba y `returning id` lo devolvía. Sin
    RETURNING, generarlo antes de insertar es la forma limpia de saberlo: se
    inserta con él y ya se conoce, sin una segunda consulta.
    """
    return uuid.uuid4()


def lista(valores) -> tuple:
    """Parámetro para `IN %s`. Nunca vacío: `IN ()` es un error de sintaxis.

    En PostgreSQL se escribía `= any(%s)` con una lista. En MySQL es
    `IN %s` con una tupla. Una lista vacía no coincide con nada, que es lo
    mismo que hacía `any` con un arreglo vacío: se representa con un valor
    que ninguna columna puede tener.
    """
    valores = tuple(str(v) if isinstance(v, uuid.UUID) else v for v in valores)
    return valores if valores else ("\x00sin-valores\x00",)


def booleanos(filas: list[dict[str, Any]], *claves: str) -> list[dict[str, Any]]:
    """Pone como true/false las columnas booleanas CALCULADAS.

    Una columna BOOLEAN de una tabla ya llega como bool (ver _convertir_fila),
    pero una expresión como `autorizado_por IS NOT NULL AS es_reemision` MySQL
    la entrega como 1 o 0, sin rastro de que era una condición. PostgreSQL
    devolvía true/false, y la pantalla compara con eso.
    """
    for fila in filas:
        for clave in claves:
            if fila.get(clave) is not None:
                fila[clave] = bool(fila[clave])
    return filas
