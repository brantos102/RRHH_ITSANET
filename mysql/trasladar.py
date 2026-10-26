"""Traslado de los datos de Supabase (PostgreSQL) a MySQL, el día del corte.

    python mysql/trasladar.py              # revisa, no toca nada
    python mysql/trasladar.py --aplicar    # traslada

El origen se lee de la variable PG_ORIGEN_URL (o de --origen). La variable es
preferible: lo que va en la línea de comandos lo puede ver cualquier usuario
del servidor mientras el proceso corre, y la cadena lleva la clave.

El destino es MYSQL_URL (o servidor/.env), con todas las migraciones de
mysql/migraciones ya aplicadas y SIN datos de personas: el traslado se niega
a escribir encima de una base que ya tiene fichas, solicitudes o bitácora.

QUÉ GARANTIZA

  Todo o nada.         Se copia en UNA transacción. Si una sola fila falla
                       —un texto demasiado largo, una cédula inválida—, se
                       deshace todo y el destino queda vacío como estaba,
                       con el motivo en pantalla.
  Nada se inventa.     Con @migrando = 1 los disparadores no deducen ni
                       generan nada: región, saldo, fines de semana,
                       bitácora y avisos se copian tal como están en origen.
  Nada queda suelto.   Las claves foráneas se desactivan durante la carga
                       (users.jefe_id apunta a la propia tabla) y, antes de
                       confirmar, se comprueba cada una: si una fila apunta
                       a algo que no existe, se deshace todo.
  Lo copiado es igual. Después de confirmar se lee cada tabla de las dos
                       bases y se compara VALOR POR VALOR, no solo cuántas
                       filas hay. Si algo difiere, lo dice con la tabla, la
                       fila y la columna.
  Los folios siguen.   Los contadores continúan desde donde iban en
                       Supabase: un folio emitido no se vuelve a emitir.

Los datos de referencia que trae la instalación (parámetros, tipos de
permiso, normas legales...) se reemplazan por los de origen: manda lo que
Talento Humano dejó configurado en producción.

Los adjuntos (archivos) no van en la base: se traen aparte con
mysql/traer_adjuntos.py.

Necesita psycopg para leer el origen:  pip install "psycopg[binary]"
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import ipaddress
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conexion  # noqa: E402
import migrar  # noqa: E402
from convertir import ECUADOR, a_mysql  # noqa: E402

VERDE, AMARILLO, ROJO, GRIS, FIN = "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[0m"

# Las que trae la instalación (0003_datos_base.sql). En el traslado se
# reemplazan por las de origen.
REFERENCIA = [
    "regiones", "ciudades_region", "legal_references", "app_config", "permission_categories",
    "permission_types", "antiguedad_referencia", "campos_ficha", "lineamientos_solicitud",
    "panel_bloques", "tablero_bloques", "feriados",
]
# Propias de MySQL, sin equivalente en origen.
SOLO_DESTINO = {"schema_migraciones", "secuencias"}
# Contadores de PostgreSQL que en MySQL son la tabla `secuencias`.
SECUENCIAS_PROPIAS = {"informes_firmados_folio_seq": "informes_firmados_folio"}
# Contadores que en PostgreSQL no pertenecen a una columna (los usa un
# disparador) y en MySQL son el AUTO_INCREMENT de esta tabla. Sin esto, los
# folios de solicitud seguirían desde el mayor que EXISTE y no desde el
# último EMITIDO: una solicitud borrada dejaría su folio libre para otra.
SECUENCIAS_DE_TABLA = {"requests_folio_seq": "requests"}

LOTE = 1000


class TrasladoFallido(Exception):
    pass


# ------------------------------------------------------------ estructura
def tablas_destino(cur) -> dict[str, dict]:
    """Cada tabla del destino: sus columnas copiables, su clave primaria y
    qué columnas son booleanas o JSON (para comparar después)."""
    cur.execute("""SELECT table_name FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'""")
    tablas = {}
    for (nombre,) in cur.fetchall():
        if nombre in SOLO_DESTINO:
            continue
        cur.execute("""SELECT column_name, column_type, data_type, extra
                         FROM information_schema.columns
                        WHERE table_schema = DATABASE() AND table_name = %s
                        ORDER BY ordinal_position""", (nombre,))
        columnas, booleanas, jsons = [], set(), set()
        for col, tipo, dato, extra in cur.fetchall():
            # VIRTUAL/STORED GENERATED se calcula sola: no se copia. Ojo:
            # DEFAULT_GENERATED solo indica un valor por omisión con
            # expresión (UUID(), la hora actual) y esa columna SÍ se copia.
            if any(g in (extra or "").upper() for g in ("VIRTUAL GENERATED", "STORED GENERATED")):
                continue
            columnas.append(col)
            if tipo.lower() == "tinyint(1)":
                booleanas.add(col)
            if dato.lower() == "json":
                jsons.add(col)
        cur.execute("""SELECT column_name FROM information_schema.key_column_usage
                        WHERE table_schema = DATABASE() AND table_name = %s
                          AND constraint_name = 'PRIMARY' ORDER BY ordinal_position""", (nombre,))
        pk = [r[0] for r in cur.fetchall()]
        tablas[nombre] = {"columnas": columnas, "pk": pk, "booleanas": booleanas, "jsons": jsons}
    return tablas


def columnas_origen(pg, tabla: str) -> dict[str, str]:
    filas = pg.execute(
        """select column_name, data_type from information_schema.columns
            where table_schema = 'public' and table_name = %s""", (tabla,)).fetchall()
    return {f[0]: f[1] for f in filas}


def select_origen(tabla: str, columnas: list[str], tipos: dict[str, str]) -> str:
    """Lo que se lee de origen. Los enumerados salen como texto y los
    arreglos de enumerados como arreglos de texto: psycopg no conoce los
    tipos propios de la base y los entregaría como «{admin,rrhh}»."""
    partes = []
    for c in columnas:
        if tipos[c] == "ARRAY":
            partes.append(f'"{c}"::text[] as "{c}"')
        elif tipos[c] == "USER-DEFINED":
            partes.append(f'"{c}"::text as "{c}"')
        else:
            partes.append(f'"{c}"')
    return f'select {", ".join(partes)} from public."{tabla}"'


def claves_foraneas(cur) -> list[tuple[str, str, str, str]]:
    cur.execute("""SELECT k.table_name, k.column_name, k.referenced_table_name, k.referenced_column_name
                     FROM information_schema.key_column_usage k
                    WHERE k.table_schema = DATABASE() AND k.referenced_table_name IS NOT NULL""")
    return list(cur.fetchall())


# ----------------------------------------------------------- comparación
def comparable(valor: Any, booleana: bool = False, es_json: bool = False) -> Any:
    """Un valor de cualquiera de las dos bases, en una forma comparable."""
    if valor is None:
        return None
    if es_json:
        if isinstance(valor, (str, bytes)):
            valor = json.loads(valor)
        return json.dumps(valor, sort_keys=True, ensure_ascii=False)
    if booleana:
        return bool(valor)
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, dt.datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(ECUADOR).replace(tzinfo=None)
        return valor
    if isinstance(valor, dt.timedelta):          # PyMySQL entrega TIME así
        return (dt.datetime.min + valor).time()
    if isinstance(valor, (int, float, decimal.Decimal)):
        return decimal.Decimal(str(valor)).normalize()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, (ipaddress.IPv4Address, ipaddress.IPv6Address,
                          ipaddress.IPv4Interface, ipaddress.IPv6Interface)):
        return str(valor)
    return valor


def _orden(clave: tuple) -> tuple:
    return tuple((v is None, str(v)) for v in clave)


def comparar_tabla(pg, cur, tabla: str, info: dict, tipos: dict) -> list[str]:
    """Las diferencias entre origen y destino en una tabla. Vacía si son iguales."""
    columnas = info["columnas"]
    pk = info["pk"] or columnas
    de_pg = pg.execute(select_origen(tabla, columnas, tipos)).fetchall()
    cur.execute(f"SELECT {', '.join(f'`{c}`' for c in columnas)} FROM `{tabla}`")
    de_my = cur.fetchall()

    def indexar(filas):
        resultado = {}
        for f in filas:
            normal = tuple(comparable(v, c in info["booleanas"], c in info["jsons"])
                           for c, v in zip(columnas, f))
            clave = tuple(normal[columnas.index(c)] for c in pk)
            resultado[clave] = normal
        return resultado

    a, b = indexar(de_pg), indexar(de_my)
    problemas = []
    if len(de_pg) != len(de_my):
        problemas.append(f"{tabla}: {len(de_pg)} filas en origen, {len(de_my)} en destino")
    for clave in sorted(set(a) | set(b), key=_orden):
        if clave not in b:
            problemas.append(f"{tabla} {clave}: falta en destino")
        elif clave not in a:
            problemas.append(f"{tabla} {clave}: sobra en destino")
        elif a[clave] != b[clave]:
            for c, x, y in zip(columnas, a[clave], b[clave]):
                if x != y:
                    problemas.append(f"{tabla} {clave}.{c}: origen {x!r} · destino {y!r}")
        if len(problemas) > 20:
            problemas.append(f"{tabla}: … (más diferencias sin listar)")
            break
    return problemas


# --------------------------------------------------------------- traslado
def revisar(pg, cur, tablas: dict) -> tuple[list[str], list[str], dict[str, dict]]:
    """Lo que impide trasladar, lo que conviene saber, y los tipos de origen."""
    errores, avisos, tipos = [], [], {}

    cur.execute("SELECT archivo FROM schema_migraciones")
    aplicadas = {r[0] for r in cur.fetchall()}
    faltan = [r.name for r in migrar.archivos() if r.name not in aplicadas]
    if faltan:
        errores.append("Al destino le faltan migraciones: " + ", ".join(faltan)
                       + ". Aplíquelas antes con  python mysql/migrar.py --aplicar")

    for tabla, info in tablas.items():
        origen = columnas_origen(pg, tabla)
        if not origen:
            avisos.append(f"{tabla}: no existe en origen; queda vacía")
            continue
        tipos[tabla] = origen
        perdidas = sorted(set(origen) - set(info["columnas"]) - _generadas_origen(pg, tabla))
        if perdidas:
            errores.append(f"{tabla}: el destino no tiene las columnas {perdidas}; se perderían")
        nuevas = [c for c in info["columnas"] if c not in origen]
        if nuevas:
            avisos.append(f"{tabla}: columnas sin equivalente en origen, quedan con su valor por omisión: {nuevas}")
        if tabla not in REFERENCIA:
            cur.execute(f"SELECT COUNT(*) FROM `{tabla}`")
            if cur.fetchone()[0]:
                errores.append(f"{tabla}: el destino ya tiene datos. El traslado solo escribe "
                               "sobre una base recién creada.")
    return errores, avisos, tipos


def _generadas_origen(pg, tabla: str) -> set[str]:
    filas = pg.execute("""select column_name from information_schema.columns
                           where table_schema = 'public' and table_name = %s
                             and is_generated = 'ALWAYS'""", (tabla,)).fetchall()
    return {f[0] for f in filas}


def copiar(pg, my, tablas: dict, tipos: dict) -> dict[str, int]:
    """Copia todo en una transacción. Devuelve las filas copiadas por tabla."""
    cur = my.cursor()
    cur.execute("SET @migrando = 1")
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    my.begin()
    copiadas = {}
    try:
        orden = [t for t in REFERENCIA if t in tablas] + sorted(t for t in tablas if t not in REFERENCIA)
        for tabla in orden:
            if tabla not in tipos:
                continue
            info = tablas[tabla]
            columnas = [c for c in info["columnas"] if c in tipos[tabla]]
            if tabla in REFERENCIA:
                # Manda lo de producción: se vacía lo que trajo la instalación.
                # Ninguna tabla con datos de personas apunta todavía a estas.
                cur.execute(f"DELETE FROM `{tabla}`")
            marcas = ", ".join(["%s"] * len(columnas))
            insert = (f"INSERT INTO `{tabla}` ({', '.join(f'`{c}`' for c in columnas)}) "
                      f"VALUES ({marcas})")
            n = 0
            with pg.cursor(name=f"traslado_{tabla}") as lector:
                lector.itersize = LOTE
                lector.execute(select_origen(tabla, columnas, tipos[tabla]))
                while True:
                    lote = lector.fetchmany(LOTE)
                    if not lote:
                        break
                    try:
                        cur.executemany(insert, [tuple(a_mysql(v) for v in fila) for fila in lote])
                    except Exception as exc:
                        raise TrasladoFallido(f"{tabla}: {exc}") from exc
                    n += len(lote)
            copiadas[tabla] = n
            print(f"  {tabla:<32} {n:>7} {GRIS}filas{FIN}")

        sueltas = []
        for hija, col, madre, col_madre in claves_foraneas(cur):
            cur.execute(f"""SELECT COUNT(*) FROM `{hija}` h LEFT JOIN `{madre}` m
                              ON m.`{col_madre}` = h.`{col}`
                             WHERE h.`{col}` IS NOT NULL AND m.`{col_madre}` IS NULL""")
            n = cur.fetchone()[0]
            if n:
                sueltas.append(f"{hija}.{col} → {madre}: {n} fila(s) apuntan a algo que no existe")
        if sueltas:
            raise TrasladoFallido("Referencias rotas:\n    " + "\n    ".join(sueltas))

        my.commit()
    except BaseException:
        my.rollback()
        raise
    finally:
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cur.execute("SET @migrando = NULL")
    return copiadas


def continuar_contadores(pg, cur) -> list[str]:
    """Los folios siguen desde donde iban. ALTER TABLE confirma por su cuenta,
    por eso va después de la transacción de los datos."""
    hechos = []
    for seq, ultimo, llamado in pg.execute(
            "select sequencename, last_value, last_value is not null from pg_sequences "
            "where schemaname = 'public'").fetchall():
        if not llamado:
            continue
        if seq in SECUENCIAS_PROPIAS:
            cur.execute("INSERT INTO secuencias (nombre, valor) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE valor = GREATEST(valor, VALUES(valor))",
                        (SECUENCIAS_PROPIAS[seq], ultimo))
            hechos.append(f"{SECUENCIAS_PROPIAS[seq]} → {ultimo}")
            continue
        dueno = pg.execute(
            """select c.relname, a.attname from pg_depend d
                 join pg_class s on s.oid = d.objid and s.relname = %s
                 join pg_class c on c.oid = d.refobjid
                 join pg_attribute a on a.attrelid = c.oid and a.attnum = d.refobjsubid
                where d.deptype in ('a', 'i')""", (seq,)).fetchone()
        if dueno is not None:
            tabla = dueno[0]
        elif seq in SECUENCIAS_DE_TABLA:
            tabla = SECUENCIAS_DE_TABLA[seq]
        else:
            continue
        cur.execute("""SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
                         AND table_name = %s AND extra LIKE '%%auto_increment%%'""", (tabla,))
        if cur.fetchone()[0]:
            cur.execute(f"ALTER TABLE `{tabla}` AUTO_INCREMENT = {int(ultimo) + 1}")
            hechos.append(f"{tabla} → sigue en {int(ultimo) + 1}")
    return hechos


def principal(origen: str, aplicar: bool, destino: str | None = None) -> int:
    try:
        import psycopg
    except ImportError:
        print(f"{ROJO}Falta psycopg para leer el origen:{FIN}  pip install \"psycopg[binary]\"")
        return 2

    print(f"\n{GRIS}Origen:  {_sin_clave(origen)}{FIN}")
    print(f"{GRIS}Destino: {conexion.describir(destino)}{FIN}\n")
    # prepare_threshold=None: el pooler de Supabase en modo transacción no
    # admite sentencias preparadas, y psycopg las prepara solo a partir de la
    # quinta vez que repite una consulta (aquí, una por tabla).
    pg = psycopg.connect(origen, prepare_threshold=None)
    # Una sola foto de la base para todo el traslado: lo que se copia y lo que
    # después se compara son los mismos datos aunque alguien siga usando el
    # sistema mientras tanto. Y solo lectura: el traslado no puede escribir
    # en Supabase ni por error.
    pg.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    pg.read_only = True
    pg.execute("set time zone 'UTC'")
    my = migrar.conectar(destino)
    cur = my.cursor()

    problemas = migrar.comprobar_servidor(cur)
    if problemas:
        print(f"{ROJO}El servidor MySQL no está listo:{FIN}")
        for p in problemas:
            print(f"  · {p}")
        return 2

    tablas = tablas_destino(cur)
    errores, avisos, tipos = revisar(pg, cur, tablas)
    for a in avisos:
        print(f"{AMARILLO}  · {a}{FIN}")
    if errores:
        print(f"\n{ROJO}No se puede trasladar. No se tocó nada:{FIN}")
        for e in errores:
            print(f"  · {e}")
        return 2

    total = sum(pg.execute(f'select count(*) from public."{t}"').fetchone()[0] for t in tipos)
    print(f"Listo para trasladar {total} filas de {len(tipos)} tablas.")
    if not aplicar:
        print(f"\n{GRIS}Esto no tocó nada. Para trasladar:{FIN}\n"
              f"    python mysql/trasladar.py --aplicar")
        return 0

    print()
    try:
        copiar(pg, my, tablas, tipos)
    except TrasladoFallido as exc:
        print(f"\n{ROJO}El traslado se deshizo entero; el destino quedó como estaba.{FIN}\n  {exc}")
        return 1

    print(f"\n{GRIS}Contadores:{FIN}")
    for h in continuar_contadores(pg, cur):
        print(f"  {h}")

    print(f"\n{GRIS}Comprobando, valor por valor, que lo copiado es igual al origen…{FIN}")
    diferencias = []
    for tabla in tipos:
        diferencias += comparar_tabla(pg, cur, tabla, tablas[tabla], tipos[tabla])
    if diferencias:
        print(f"{ROJO}Lo copiado NO coincide con el origen:{FIN}")
        for d in diferencias:
            print(f"  · {d}")
        print(f"\n{AMARILLO}No ponga el sistema en marcha sobre esta base. "
              f"Bórrela, corrija y repita el traslado.{FIN}")
        return 1

    print(f"{VERDE}Traslado completo: {total} filas, todas iguales al origen.{FIN}")
    return 0


def _sin_clave(url: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"{u.scheme}://{u.username or ''}@{u.hostname or ''}{':' + str(u.port) if u.port else ''}{u.path}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--origen", help="URL de PostgreSQL (Supabase). Mejor por la variable "
                    "PG_ORIGEN_URL: en la línea de comandos la ven los demás usuarios del servidor")
    ap.add_argument("--aplicar", action="store_true", help="trasladar de verdad")
    args = ap.parse_args()
    import os
    origen = args.origen or os.environ.get("PG_ORIGEN_URL")
    if not origen:
        ap.error("falta el origen: defina PG_ORIGEN_URL o use --origen")
    sys.exit(principal(origen, args.aplicar))
