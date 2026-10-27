"""Pruebas contra una base MySQL real (no simulada).

Se apuntan a una base local de pruebas, construida con las migraciones de
mysql/migraciones; nunca a la de producción. El correo se intercepta para
leer el código sin enviarlo.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pymysql
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault(
    "MYSQL_URL",
    "mysql://root@localhost/rrhh_pruebas?unix_socket=/var/run/mysqld/mysqld.sock",
)
os.environ.setdefault("JWT_SECRET", "secreto-de-prueba-suficientemente-largo-1234")
# Los adjuntos de las pruebas van a una carpeta temporal, nunca a la real.
os.environ.setdefault("ADJUNTOS_DIR", tempfile.mkdtemp(prefix="rrhh-adjuntos-prueba-"))
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("ENTORNO", "desarrollo")
# El límite de envíos de código es por cédula y, multiplicado por cuatro, por
# IP. Todas las pruebas salen de la misma IP, así que con el valor de
# producción (5, o sea 20 por IP) la suite se bloqueaba a sí misma en cuanto
# algo más había iniciado sesión desde esta máquina en la última hora: las
# pruebas de navegador dejaban el contador alto y aquí empezaban a llover
# 429 en el arranque de cada prueba. El límite se prueba aparte, leyendo este
# mismo valor en vez de suponerlo.
os.environ.setdefault("OTP_MAX_ENVIOS_HORA", "50")

import httpx  # noqa: E402
from app import correo  # noqa: E402
from app.db import ejecutar, lista, nuevo_id, obtener_uno, transaccion  # noqa: E402
from app.main import app  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mysql"))
import migrar  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def base_de_pruebas_mysql():
    """La base de pruebas, al día con las migraciones de mysql/migraciones.

    Se crea si no existe y se le aplican las migraciones que le falten: las
    pruebas corren siempre contra el mismo esquema que irá a producción.

    Se niega a tocar una base cuyo nombre no diga «prueba». Las pruebas
    borran y crean filas a voluntad; apuntarlas por error a la base real
    sería borrar datos de personas reales.
    """
    url = os.environ["MYSQL_URL"]
    nombre = urlparse(url).path.lstrip("/")
    if "prueba" not in nombre:
        pytest.exit(f"MYSQL_URL apunta a «{nombre}», que no es una base de pruebas. "
                    "Las pruebas solo corren contra una base cuyo nombre diga «prueba».",
                    returncode=2)
    u = urlparse(url)
    consulta = parse_qs(u.query)
    raiz = pymysql.connect(host=u.hostname or "localhost", port=u.port or 3306,
                           user=unquote(u.username or ""), password=unquote(u.password or ""),
                           unix_socket=consulta.get("unix_socket", [None])[0],
                           charset="utf8mb4", autocommit=True)
    raiz.cursor().execute(f"CREATE DATABASE IF NOT EXISTS `{nombre}` "
                          "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    raiz.close()
    if migrar.principal(aplicar=True, url=url) != 0:
        pytest.exit("Las migraciones no se aplicaron en la base de pruebas.", returncode=2)

    # El personal de prueba de siempre (supabase/seed.sql), si no está.
    import asyncio

    from app.db import cerrar_pool
    from semilla import sembrar

    async def _sembrar():
        try:
            await sembrar()
        finally:
            await cerrar_pool()
    asyncio.run(_sembrar())


@pytest.fixture(autouse=True)
async def _pool_por_prueba():
    """Cada prueba corre en su propio bucle de eventos, y un pool de aiomysql
    pertenece al bucle que lo abrió: se cierra al final de cada prueba, en su
    mismo bucle, para no dejar conexiones huérfanas."""
    yield
    from app.db import cerrar_pool
    await cerrar_pool()

CEDULA_PRUEBA = "1700000001"
CEDULA_SIN_REGISTRO = "0900000001"
CORREO_PRUEBA = "prueba@api.test"


@pytest.fixture
def codigos(monkeypatch) -> list[str]:
    """Captura el OTP en lugar de enviarlo por correo."""
    capturados: list[str] = []

    async def falso_envio(destinatario: str, nombre: str, codigo: str) -> None:
        capturados.append(codigo)

    monkeypatch.setattr(correo, "enviar_otp", falso_envio)
    return capturados


@pytest.fixture
async def cliente(empleado):
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        yield c


@pytest.fixture
async def empleado():
    """Crea un empleado de prueba y limpia todo lo que la prueba genere."""
    await _limpiar()
    user_id = str(nuevo_id())
    await ejecutar(
        """INSERT INTO users (id, cedula, nombre, email, rol, fecha_ingreso, telefono)
           VALUES (%s, %s, 'API Empleado', %s, 'empleado',
                   CURRENT_DATE() - INTERVAL 7 YEAR, '0999123456')""",
        (user_id, CEDULA_PRUEBA, CORREO_PRUEBA),
    )
    # Saldo realista: sin esto acumularía los 7 años completos (108 días)
    from app.reglas import periodos
    await periodos.cargar_saldo_inicial(user_id, 12.5, 0)
    yield {"id": user_id, "cedula": CEDULA_PRUEBA, "email": CORREO_PRUEBA}
    await _limpiar()


async def _limpiar() -> None:
    cedulas = lista([CEDULA_PRUEBA, CEDULA_SIN_REGISTRO, "0900000001", "1100000007", "1200000006"])
    async with transaccion():
        # La bitácora es inmutable: borrar de ella exige la retención
        # autorizada, encendida y apagada en esta misma conexión.
        await ejecutar("SET @retencion = 'autorizada'")
        try:
            # Los códigos de acceso se borran por dueño y no por una lista fija
            # de cédulas: el límite de envíos cuenta por hora, y cada módulo de
            # pruebas crea su propio jefe, su guardia o su Talento Humano. Con
            # una lista cerrada, esas cédulas acumulaban envíos hasta que el
            # fixture recibía un 429 sin que nada estuviera roto.
            await ejecutar(
                """DELETE FROM auth_otp
                    WHERE cedula IN %s
                       OR cedula IN (SELECT cedula FROM users
                                      WHERE email LIKE '%%@api.test' OR email LIKE '%%@itsanet.test')""",
                (cedulas,))
            await ejecutar(
                "DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email LIKE %s)",
                ("%@api.test",))
            await ejecutar("DELETE FROM audit_logs WHERE cedula IN %s", (cedulas,))
            # Los intentos fallidos de identificarse se registran con una cédula
            # que no corresponde a nadie, así que la limpieza de arriba no los
            # alcanza; el alta se cierra tras diez por hora desde la misma red.
            await ejecutar("DELETE FROM audit_logs WHERE accion = 'alta_identidad_fallida'")
        finally:
            await ejecutar("SET @retencion = NULL")
    # Los ajustes apuntan a quien los hizo y la clave foránea es restrictiva a
    # propósito: en producción las personas se desactivan, no se borran.
    await ejecutar(
        "DELETE FROM request_adjustments WHERE ajustado_por IN (SELECT id FROM users WHERE email LIKE %s)",
        ("%@api.test",))
    await ejecutar("DELETE FROM visitors WHERE motivo_visita LIKE %s", ("%de prueba%",))
    await ejecutar("DELETE FROM visitors WHERE nombre LIKE %s", ("Proveedor de prueba%",))
    # También por cédula: una prueba que cambie el correo de un usuario de
    # prueba lo dejaba fuera de esta limpieza y rompía a las siguientes.
    await ejecutar(
        "DELETE FROM users WHERE cedula IN %s",
        (lista([CEDULA_PRUEBA, "0900000001", "1100000007", "1200000006",
                "1700000019", "1700000027", "1700000035"]),))
    await ejecutar("DELETE FROM users WHERE email LIKE %s", ("%@api.test",))
    await ejecutar("DELETE FROM users WHERE email LIKE %s", ("%@empresa-prueba.com",))


# ------------------------------------------------- ayudantes para MySQL
# PostgreSQL devolvía la fila con INSERT ... RETURNING y resolvía el choque
# con ON CONFLICT. MySQL no tiene RETURNING: estos ayudantes hacen lo mismo
# para las pruebas, sin que cada una repita la receta.
class Sql(str):
    """Un valor que va como expresión SQL y no como dato: Sql("CURRENT_DATE()")."""


async def insertar(tabla: str, **campos) -> dict:
    """INSERT ... RETURNING *: inserta y devuelve la fila como quedó."""
    import re
    import uuid as _uuid

    from app.db import insertar as _insertar
    assert re.fullmatch(r"[a-z_]+", tabla) and all(re.fullmatch(r"[a-z_]+", c) for c in campos)
    columna_id = await obtener_uno(
        """SELECT data_type AS data_type, extra AS extra FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = %s AND column_name = 'id'""", (tabla,))
    if columna_id and columna_id["data_type"] == "char" and "id" not in campos:
        campos["id"] = str(_uuid.uuid4())
    marcas = ", ".join(v if isinstance(v, Sql) else "%s" for v in campos.values())
    valores = tuple(v for v in campos.values() if not isinstance(v, Sql))
    generado = await _insertar(f"INSERT INTO {tabla} ({', '.join(campos)}) VALUES ({marcas})", valores)
    clave = campos.get("id", generado)
    if columna_id is None:
        return dict(campos)
    return await obtener_uno(f"SELECT * FROM {tabla} WHERE id = %s", (clave,))


async def persona(cedula: str, al_existir: dict | None = None, **campos) -> dict:
    """Una persona de prueba por cédula: la crea, o actualiza la que ya está.

    Es el `insert ... on conflict (cedula) do update set <al_existir>
    returning id` de las pruebas escritas para PostgreSQL: si ya existe, solo
    cambia lo de `al_existir` (nada, si no se da). Por omisión entró hace 900 días.
    """
    campos.setdefault("fecha_ingreso", Sql("CURRENT_DATE() - INTERVAL 900 DAY"))
    ya = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (cedula,))
    if ya is None:
        return await insertar("users", cedula=cedula, **campos)
    cambios = dict(al_existir or {})
    if cambios:
        asignaciones = ", ".join(f"{c} = {v}" if isinstance(v, Sql) else f"{c} = %s" for c, v in cambios.items())
        await ejecutar(f"UPDATE users SET {asignaciones} WHERE id = %s",
                       (*[v for v in cambios.values() if not isinstance(v, Sql)], ya["id"]))
    return await obtener_uno("SELECT * FROM users WHERE id = %s", (ya["id"],))
