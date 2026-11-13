"""Cada sesión de pruebas crea una base MySQL desechable desde cero.

No se prueba contra una base que alguien preparó a mano: se aplican las
migraciones de mysql/migraciones/ sobre una base vacía, exactamente como se
hará en el servidor. Si una migración no funciona en limpio, aquí falla.

Por omisión usa el MySQL local por socket. Para probar contra otro:

    MYSQL_PRUEBAS_URL=mysql://usuario:clave@servidor/  pytest mysql/pruebas
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pymysql
import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
import conexion  # noqa: E402
import migrar  # noqa: E402

BASE_URL = os.environ.get(
    "MYSQL_PRUEBAS_URL", "mysql://root@localhost/?unix_socket=/var/run/mysqld/mysqld.sock")


def _url(base: str) -> str:
    sin, _, consulta = BASE_URL.partition("?")
    sin = sin.rstrip("/") + "/" + base
    return sin + ("?" + consulta if consulta else "")


@pytest.fixture(scope="session")
def base_de_pruebas():
    nombre = f"rrhh_prueba_{uuid.uuid4().hex[:8]}"
    p = conexion.parametros(_url(""))
    raiz = pymysql.connect(host=p["host"], port=p["port"], user=p["user"], password=p["password"],
                           unix_socket=p.get("unix_socket"), charset="utf8mb4", autocommit=True)
    raiz.cursor().execute(
        f"CREATE DATABASE {nombre} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    url = _url(nombre)
    assert migrar.principal(aplicar=True, url=url) == 0, "las migraciones no aplican en limpio"
    yield url
    raiz.cursor().execute(f"DROP DATABASE {nombre}")
    raiz.close()


@pytest.fixture
def db(base_de_pruebas):
    """Una conexión dentro de una transacción que se deshace al terminar.

    Así cada prueba deja la base como la encontró y no depende del orden.
    """
    con = migrar.conectar(base_de_pruebas)
    con.autocommit(False)
    cur = con.cursor(pymysql.cursors.DictCursor)
    yield cur
    con.rollback()
    con.close()


def error_de(exc_info) -> tuple[int, str]:
    """El número y el texto de un error de MySQL."""
    return exc_info.value.args[0], exc_info.value.args[1]
