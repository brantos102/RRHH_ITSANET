"""La cadena de conexión a MySQL, leída en un solo sitio.

Formato, el mismo que usan casi todas las herramientas:

    mysql://usuario:clave@servidor:3306/rrhh
    mysql://usuario:clave@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock

Se lee de la variable MYSQL_URL o, si no está, del archivo servidor/.env.

EL JUEGO DE CARACTERES NO ES OPCIONAL. Probado en este proyecto: un cliente
que no declara utf8mb4 guarda «Suárez» corrompido, sin dar ningún error, y
después no aparece al buscar «suarez». Toda conexión que salga de aquí lleva
utf8mb4, y la zona horaria de Ecuador.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = Path(__file__).resolve().parents[1]

# Ecuador continental no tiene horario de verano desde 1993. Una zona fija
# por desplazamiento no depende de que el servidor tenga cargadas las tablas
# de zonas horarias de MySQL, que en una instalación nueva suelen faltar.
ZONA_ECUADOR = "-05:00"


def _desde_env_archivo() -> str | None:
    archivo = RAIZ / "servidor" / ".env"
    if not archivo.exists():
        return None
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea.startswith("MYSQL_URL="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def url_mysql() -> str:
    url = os.environ.get("MYSQL_URL") or _desde_env_archivo()
    if not url:
        raise SystemExit(
            "Falta MYSQL_URL. Defínala en servidor/.env o como variable de entorno, por ejemplo:\n"
            "    MYSQL_URL=mysql://rrhh_app:CLAVE@localhost:3306/rrhh")
    return url


def parametros(url: str | None = None) -> dict:
    """Los argumentos de conexión para PyMySQL / aiomysql."""
    u = urlparse(url or url_mysql())
    if u.scheme not in ("mysql", "mysql+pymysql", "mysql+aiomysql"):
        raise SystemExit(f"MYSQL_URL tiene que empezar por mysql://, no por {u.scheme}://")
    consulta = parse_qs(u.query)
    p = {
        "host": u.hostname or "localhost",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "db": (u.path or "/").lstrip("/") or None,
        "charset": "utf8mb4",
        "init_command": f"SET time_zone = '{ZONA_ECUADOR}', NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci",
    }
    if "unix_socket" in consulta:
        p["unix_socket"] = consulta["unix_socket"][0]
    return p


def describir(url: str | None = None) -> str:
    """La URL sin la clave, para mostrarla en pantalla."""
    u = urlparse(url or url_mysql())
    usuario = unquote(u.username or "")
    return f"mysql://{usuario}@{u.hostname or 'localhost'}{':' + str(u.port) if u.port else ''}{u.path}"
