"""Acceso a PostgreSQL con pool asíncrono.

El backend se conecta con credenciales de servicio, por lo que **no pasa
por RLS**: cada consulta debe filtrar explícitamente por el usuario. El
frontend, en cambio, usa supabase-js con el JWT que emite este backend, y
ahí sí aplican las políticas.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

_pool: AsyncConnectionPool | None = None


async def abrir_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = AsyncConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row, "application_name": "rrhh-api"},
        )
        await _pool.open(wait=True, timeout=10)
    return _pool


async def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def conexion():
    pool = await abrir_pool()
    async with pool.connection() as conn:
        yield conn


async def obtener_uno(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def obtener_todos(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def ejecutar(sql: str, params: tuple | dict = ()) -> int:
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.rowcount
