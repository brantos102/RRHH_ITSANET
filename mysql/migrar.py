"""Aplica a MySQL las migraciones que le falten, en orden y sin repetir.

    python mysql/migrar.py                 dice qué falta, no toca nada
    python mysql/migrar.py --aplicar       lo aplica

Las migraciones están en mysql/migraciones/, numeradas. Usan `DELIMITER`
igual que el cliente `mysql`, así que TI también puede aplicarlas a mano:

    mysql --default-character-set=utf8mb4 rrhh < mysql/migraciones/0001_esquema.sql

Si lo hace a mano, después ejecute este guion con --aplicar: verá las
aplicadas a mano como pendientes, las volverá a ejecutar —son idempotentes—
y quedarán anotadas.

LO QUE MYSQL NO PERMITE Y HAY QUE SABER. En MySQL, crear o modificar una
tabla confirma la transacción en curso por su cuenta: no hay forma de
deshacer una migración a medias. Si una falla, las sentencias anteriores de
ese mismo archivo ya quedaron aplicadas. Por eso cada migración está escrita
para poder ejecutarse de nuevo sin romper nada (CREATE ... IF NOT EXISTS,
DROP ... IF EXISTS antes de crear), y el guion dice en qué sentencia se
detuvo.

Antes de aplicar sobre datos reales: respaldo.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conexion  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
CARPETA = Path(__file__).resolve().parent / "migraciones"

# Sentencias que en MySQL confirman la transacción por su cuenta.
DDL = re.compile(r"^\s*(CREATE|ALTER|DROP|RENAME|TRUNCATE)\b", re.IGNORECASE)


def archivos() -> list[Path]:
    return sorted(CARPETA.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]


def sentencias(sql: str) -> list[str]:
    """Trocea un archivo SQL respetando `DELIMITER`, como el cliente mysql.

    El delimitador por omisión es `;`. Una línea `DELIMITER $$` lo cambia, y
    a partir de ahí una sentencia termina donde aparece `$$`. Así es como se
    escriben los disparadores y funciones, cuyo cuerpo lleva `;` por dentro.

    Dentro de cada tramo se respetan los textos entre comillas y los
    comentarios: un delimitador dentro de ellos no corta.
    """
    fuera: list[str] = []
    actual: list[str] = []
    delim = ";"
    for linea in sql.splitlines(keepends=True):
        m = re.match(r"^\s*DELIMITER\s+(\S+)\s*$", linea, re.IGNORECASE)
        if m:
            if "".join(actual).strip():
                fuera.append("".join(actual))
            actual = []
            delim = m.group(1)
            continue
        actual.append(linea)
        texto = "".join(actual)
        # ¿Termina esta línea una sentencia? Solo si el delimitador está al
        # final de la línea y fuera de comillas y comentarios.
        if linea.rstrip().endswith(delim) and _fuera_de_texto(texto):
            cuerpo = texto.rstrip()[: -len(delim)]
            if cuerpo.strip():
                fuera.append(cuerpo)
            actual = []
    if "".join(actual).strip():
        fuera.append("".join(actual))
    # Un trozo que solo tiene comentarios no es una sentencia.
    return [s.strip() for s in fuera if _tiene_codigo(s)]


def _fuera_de_texto(texto: str) -> bool:
    """Verdadero si el final del texto no queda dentro de una comilla."""
    dentro: str | None = None
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if dentro:
            if c == "\\" and dentro in ("'", '"'):
                i += 2
                continue
            if c == dentro:
                if i + 1 < n and texto[i + 1] == dentro:  # comilla duplicada
                    i += 2
                    continue
                dentro = None
            i += 1
            continue
        if texto.startswith("--", i) or c == "#":
            fin = texto.find("\n", i)
            if fin == -1:
                return True
            i = fin + 1
            continue
        if texto.startswith("/*", i):
            fin = texto.find("*/", i)
            if fin == -1:
                return False
            i = fin + 2
            continue
        if c in ("'", '"', "`"):
            dentro = c
        i += 1
    return dentro is None


def _tiene_codigo(s: str) -> bool:
    sin = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    sin = "\n".join(l for l in sin.splitlines() if not l.strip().startswith("--"))
    return bool(sin.strip())


def conectar(url: str | None = None):
    import pymysql
    p = conexion.parametros(url)
    return pymysql.connect(
        host=p["host"], port=p["port"], user=p["user"], password=p["password"],
        database=p["db"], charset="utf8mb4", unix_socket=p.get("unix_socket"),
        init_command=p["init_command"], autocommit=True,
        client_flag=0)


def asegurar_registro(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migraciones (
          archivo     VARCHAR(190) NOT NULL PRIMARY KEY,
          huella      CHAR(16) NOT NULL,
          aplicada_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
          COMMENT='Qué migraciones tiene puesta esta base. La lleva mysql/migrar.py.'""")


def comprobar_servidor(cur) -> list[str]:
    """Lo que el servidor tiene que cumplir antes de tocar nada.

    El modo estricto no es una preferencia. Sin él, MySQL RECORTA en silencio
    un texto que no cabe y convierte en cero un número fuera de rango, y
    devuelve éxito. Pasó en las pruebas de esta migración: el texto del
    mandato de la solicitud no cabía, y solo el modo estricto lo detuvo. Con
    los datos de 351 personas, un recorte silencioso es lo peor que puede
    pasar, porque nadie lo nota hasta que alguien reclama.
    """
    problemas = []
    cur.execute("SELECT @@version, @@sql_mode, @@character_set_server, @@collation_server")
    version, modo, juego, colacion = cur.fetchone()
    mayor = int(version.split(".")[0])
    if mayor < 8:
        problemas.append(f"MySQL {version}: hace falta 8.0 o superior.")
    if "STRICT_TRANS_TABLES" not in modo and "STRICT_ALL_TABLES" not in modo:
        problemas.append(
            "El servidor NO está en modo estricto (sql_mode sin STRICT_TRANS_TABLES). "
            "MySQL recortaría textos y números sin avisar. TI tiene que activarlo en "
            "my.cnf: sql_mode = STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
            "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION")
    cur.execute("SELECT @@character_set_database, @@collation_database")
    juego_bd, colacion_bd = cur.fetchone()
    if juego_bd != "utf8mb4":
        problemas.append(
            f"La base está en {juego_bd}, no en utf8mb4: los nombres con tilde y eñe se "
            f"corromperían. Créela con CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci.")
    return problemas


def principal(aplicar: bool, url: str | None = None) -> int:
    print(f"\n{GRIS}Base: {conexion.describir(url)}{FIN}\n")
    con = conectar(url)
    cur = con.cursor()
    problemas = comprobar_servidor(cur)
    if problemas:
        print(f"{ROJO}El servidor no está listo. No se tocó nada:{FIN}")
        for p in problemas:
            print(f"  · {p}")
        return 2
    asegurar_registro(cur)
    cur.execute("SELECT archivo, huella FROM schema_migraciones")
    ya = dict(cur.fetchall())

    todas = archivos()
    cambiadas = [r for r in todas if r.name in ya and ya[r.name] != huella(r)]
    if cambiadas:
        print(f"{AMARILLO}Estas migraciones ya aplicadas cambiaron después en el repositorio:{FIN}")
        for r in cambiadas:
            print(f"    {r.name}")
        print(f"{GRIS}    No se vuelven a ejecutar. Si el cambio importa, hace falta una nueva.{FIN}\n")

    pendientes = [r for r in todas if r.name not in ya]
    if not pendientes:
        print(f"{VERDE}La base está al día: {len(ya)} migración(es) aplicadas.{FIN}")
        return 0

    print(f"{AMARILLO}Faltan {len(pendientes)} migración(es):{FIN}")
    for r in pendientes:
        print(f"    {r.name}")
    if not aplicar:
        print(f"\n{GRIS}Esto no tocó nada. Para aplicarlas:{FIN}\n    python mysql/migrar.py --aplicar")
        print(f"\n{AMARILLO}Antes de aplicarlas sobre datos reales, saque un respaldo.{FIN}")
        return 0

    print()
    for ruta in pendientes:
        partes = sentencias(ruta.read_text(encoding="utf-8"))
        # Si el archivo no crea ni modifica estructura, va en UNA transacción
        # y entra entero o no entra nada. Con DDL no se puede: MySQL confirma
        # solo cada CREATE, ALTER o DROP.
        con_ddl = any(DDL.match(s) for s in partes)
        print(f"  {ruta.name} ({len(partes)} sentencias"
              f"{'' if con_ddl else ', en una transacción'}) … ", end="", flush=True)
        if not con_ddl:
            con.begin()
        for n, s in enumerate(partes, 1):
            try:
                cur.execute(s)
            except Exception as exc:  # noqa: BLE001
                print(f"{ROJO}falló en la sentencia {n} de {len(partes)}{FIN}")
                print(f"\n{ROJO}{exc}{FIN}")
                print(f"\n{GRIS}{s[:400]}{FIN}")
                if con_ddl:
                    print(f"\n{AMARILLO}MySQL no deshace el DDL: las {n - 1} sentencias "
                          f"anteriores de este archivo quedaron aplicadas.{FIN}")
                    print(f"{GRIS}Corrija y vuelva a ejecutar: la migración está escrita "
                          f"para poder repetirse.{FIN}")
                else:
                    con.rollback()
                    print(f"\n{VERDE}Se deshizo entera: no quedó nada a medias.{FIN}")
                return 1
        cur.execute("INSERT INTO schema_migraciones (archivo, huella) VALUES (%s, %s) AS nueva "
                    "ON DUPLICATE KEY UPDATE huella = nueva.huella, aplicada_en = CURRENT_TIMESTAMP(6)",
                    (ruta.name, huella(ruta)))
        if not con_ddl:
            con.commit()
        print(f"{VERDE}✓{FIN}")

    print(f"\n{VERDE}Listo: {len(pendientes)} migración(es) aplicadas.{FIN}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aplicar", action="store_true", help="Aplicar de verdad.")
    a = p.parse_args([x.lower() if x.lower() == "--aplicar" else x for x in sys.argv[1:]])
    raise SystemExit(principal(a.aplicar))
