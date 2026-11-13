"""Aplica a la base las migraciones que le falten, en orden y sin repetir.

Hasta hoy cada migración se pegaba a mano en el editor de Supabase. Con
cuarenta y cinco archivos eso tiene dos problemas que no avisan: saltarse uno
—y que el sistema falle semanas después por algo que parece no tener
relación—, y no saber nunca con certeza qué tiene puesto la base de
producción.

    python scripts/migrar.py                  # dice qué falta, no toca nada
    python scripts/migrar.py --aplicar        # aplica lo que falte
    python scripts/migrar.py --marcar-hasta 0041

LA PRIMERA VEZ, EN UNA BASE QUE YA ESTÁ AL DÍA. El registro empieza vacío, así
que el guion creerá que no hay ninguna aplicada. NO las aplique otra vez a
ciegas: use `--marcar-hasta` con el número de la última que usted sabe que ya
está puesta, y el guion la anota sin ejecutarla. A partir de ahí trabaja solo.

Para saber hasta dónde está su base, ejecute antes `python
scripts/verificar.py`: lista las migraciones una por una y marca las que
faltan.

CADA ARCHIVO VA EN SU PROPIA TRANSACCIÓN. Si uno falla, esa migración se
deshace entera y el guion se detiene ahí: nunca queda una a medias ni se
aplica la siguiente sobre una base en un estado que nadie previó. Las
anteriores ya aplicadas se quedan, que es lo correcto.

NO HAY MARCHA ATRÁS AUTOMÁTICA, y es deliberado. Deshacer una migración que
ya borró una columna no es un comando, es una restauración del respaldo. El
guion lo dice en vez de fingir que puede.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

MIGRACIONES = RAIZ / "supabase" / "migrations"

def numero_de(ruta: Path) -> str:
    """Los cuatro dígitos finales de la marca de tiempo: el número de orden."""
    marca = ruta.name.split("_", 1)[0]
    return marca[-4:] if marca.isdigit() else marca


def archivos() -> list[Path]:
    """Las migraciones en el orden en que hay que aplicarlas: el del nombre."""
    return sorted(MIGRACIONES.glob("*.sql"))


def huella(ruta: Path) -> str:
    """Para avisar si un archivo ya aplicado cambió después."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]


async def asegurar_registro() -> None:
    from app.db import ejecutar
    await ejecutar("""
        create table if not exists public.schema_migraciones (
          archivo     text primary key,
          numero      text not null,
          huella      text not null,
          aplicada_en timestamptz not null default now(),
          -- Verdadero cuando se anotó sin ejecutarla, porque la base ya la
          -- tenía puesta desde antes de que existiera este registro.
          solo_marcada boolean not null default false
        )""")
    await ejecutar(
        "comment on table public.schema_migraciones is "
        "'Qué migraciones tiene puesta esta base. La lleva scripts/migrar.py.'")


async def aplicadas() -> dict[str, dict]:
    from app.db import obtener_todos
    filas = await obtener_todos(
        "select archivo, huella, aplicada_en, solo_marcada from public.schema_migraciones")
    return {f["archivo"]: f for f in filas}


# PostgreSQL PROHÍBE usar un valor nuevo de un enumerado dentro de la misma
# transacción que lo añadió:
#
#     unsafe use of new value "..." of enum type ...
#     HINT: New enum values must be committed before they can be used.
#
# No es una limitación de este guion ni se puede rodear: hay dos migraciones
# que añaden un valor y lo usan a continuación, y esas tienen que ir sin
# transacción. Se detecta por el contenido y se avisa en pantalla, porque si
# una de ellas falla a la mitad sí queda a medias, y quien ejecuta tiene que
# saberlo en el momento, no descubrirlo después.
SIN_TRANSACCION = re.compile(r"alter\s+type\s+\S+\s+add\s+value", re.IGNORECASE)


def sentencias(sql: str) -> list[str]:
    """Trocea un archivo SQL en sentencias sueltas.

    Hace falta solo para las migraciones que añaden valores a un enumerado.
    Mandar el archivo entero de una vez no sirve: aunque la conexión esté en
    autoconfirmación, el servidor envuelve un bloque con varias sentencias en
    una transacción implícita, y vuelve el mismo error.

    Lo único que hay que respetar al cortar por `;` es no cortar dentro de un
    texto entre comillas ni dentro de un cuerpo entre signos de dólar
    —`$$ ... $$`, `$cuerpo$ ... $cuerpo$`—, que es donde viven las funciones y
    están llenos de puntos y comas. Los comentarios de línea también se saltan,
    porque un `;` dentro de un comentario cortaría donde no toca.
    """
    fuera: list[str] = []
    actual: list[str] = []
    i, n = 0, len(sql)
    etiqueta: str | None = None          # el $...$ que estamos dentro, si lo hay

    while i < n:
        c = sql[i]

        if etiqueta:
            if sql.startswith(etiqueta, i):
                actual.append(etiqueta)
                i += len(etiqueta)
                etiqueta = None
                continue
            actual.append(c)
            i += 1
            continue

        # Comentario de línea: hasta el salto, tal cual.
        if sql.startswith("--", i):
            fin = sql.find("\n", i)
            fin = n if fin == -1 else fin + 1
            actual.append(sql[i:fin])
            i = fin
            continue

        # Comentario de bloque.
        if sql.startswith("/*", i):
            fin = sql.find("*/", i)
            fin = n if fin == -1 else fin + 2
            actual.append(sql[i:fin])
            i = fin
            continue

        # Texto entre comillas simples, con '' como escape.
        if c == "'":
            actual.append(c)
            i += 1
            while i < n:
                actual.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        actual.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        # Apertura de un cuerpo entre signos de dólar.
        if c == "$":
            cierre = sql.find("$", i + 1)
            posible = sql[i:cierre + 1] if cierre != -1 else ""
            # $$ o $palabra$: nada raro en medio.
            if posible and (len(posible) == 2 or posible[1:-1].isidentifier()):
                actual.append(posible)
                i += len(posible)
                etiqueta = posible
                continue

        if c == ";":
            fuera.append("".join(actual))
            actual = []
            i += 1
            continue

        actual.append(c)
        i += 1

    if "".join(actual).strip():
        fuera.append("".join(actual))
    return [s for s in (x.strip() for x in fuera) if s]


async def aplicar_una(ruta: Path) -> bool:
    """Una migración, entera. Devuelve si hubo que ir sin transacción.

    El registro de que se aplicó va DENTRO de la misma transacción. Si fuera
    aparte, un corte entre una cosa y otra dejaría una migración aplicada sin
    anotar, y la siguiente ejecución intentaría aplicarla otra vez.
    """
    from app.db import conexion as abrir

    sql = ruta.read_text(encoding="utf-8")
    suelta = bool(SIN_TRANSACCION.search(sql))
    anotar = ("""insert into public.schema_migraciones (archivo, numero, huella)
                 values (%s, %s, %s)
                 on conflict (archivo) do update
                    set huella = excluded.huella, aplicada_en = now(),
                        solo_marcada = false""",
              (ruta.name, numero_de(ruta), huella(ruta)))

    async with abrir() as conn:
        if suelta:
            await conn.set_autocommit(True)
            for sentencia in sentencias(sql):
                await conn.execute(sentencia)
            await conn.execute(*anotar)
            return True
        # `psycopg` abre transacción sola; el `async with` la confirma al
        # salir bien y la deshace entera si algo revienta dentro.
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(*anotar)
    return False


async def marcar(rutas: list[Path]) -> None:
    from app.db import ejecutar
    for ruta in rutas:
        await ejecutar(
            """insert into public.schema_migraciones
                 (archivo, numero, huella, solo_marcada)
               values (%s, %s, %s, true)
               on conflict (archivo) do nothing""",
            (ruta.name, numero_de(ruta), huella(ruta)))


async def principal(aplicar: bool, marcar_hasta: str | None) -> int:
    from app.config import get_settings

    settings = get_settings()
    destino = re.sub(r"://[^@]+@", "://···@", settings.database_url or "")
    print(f"\n{GRIS}Base: {destino[:90]}{FIN}\n")

    todas = archivos()
    if not todas:
        print(f"{ROJO}No hay ninguna migración en {MIGRACIONES}{FIN}")
        return 2

    await asegurar_registro()
    ya = await aplicadas()

    # --- Anotar sin ejecutar, para adoptar una base que ya está al día ---
    if marcar_hasta:
        hasta = marcar_hasta.zfill(4)
        objetivo = [r for r in todas if numero_de(r) <= hasta and r.name not in ya]
        if not objetivo:
            print(f"{VERDE}No hay nada que marcar hasta la {hasta}.{FIN}")
            return 0
        if not aplicar:
            print(f"{AMARILLO}Se anotarían como ya aplicadas, SIN ejecutarlas:{FIN}")
            for r in objetivo:
                print(f"    {numero_de(r)}  {r.name}")
            print(f"\n{GRIS}Repita con --aplicar para anotarlas.{FIN}")
            return 0
        await marcar(objetivo)
        print(f"{VERDE}Anotadas {len(objetivo)} migración(es) hasta la {hasta}, "
              f"sin ejecutarlas.{FIN}")
        ya = await aplicadas()

    # --- Lo que cambió después de haberse aplicado ---
    cambiadas = [r for r in todas
                 if r.name in ya and ya[r.name]["huella"] != huella(r)
                 and not ya[r.name]["solo_marcada"]]
    if cambiadas:
        print(f"{AMARILLO}Estas migraciones ya aplicadas cambiaron en el "
              f"repositorio después:{FIN}")
        for r in cambiadas:
            print(f"    {numero_de(r)}  {r.name}")
        print(f"{GRIS}    No se vuelven a ejecutar. Si el cambio importa, "
              f"hace falta una migración nueva que lo arregle.{FIN}\n")

    pendientes = [r for r in todas if r.name not in ya]
    if not pendientes:
        print(f"{VERDE}La base está al día: {len(ya)} migración(es) aplicadas.{FIN}")
        return 0

    print(f"{AMARILLO}Faltan {len(pendientes)} migración(es):{FIN}")
    for r in pendientes:
        print(f"    {numero_de(r)}  {r.name}")

    if not aplicar:
        print(f"\n{GRIS}Esto no tocó nada. Para aplicarlas:{FIN}")
        print(f"    python scripts/migrar.py --aplicar")
        print(f"\n{AMARILLO}Antes de aplicarlas sobre datos reales, saque un "
              f"respaldo.{FIN}")
        return 0

    print()
    for ruta in pendientes:
        print(f"  {numero_de(ruta)}  {ruta.name} … ", end="", flush=True)
        try:
            suelta = await aplicar_una(ruta)
        except Exception as exc:  # noqa: BLE001
            print(f"{ROJO}falló{FIN}")
            print(f"\n{ROJO}{str(exc)[:600]}{FIN}")
            if SIN_TRANSACCION.search(ruta.read_text(encoding="utf-8")):
                print(f"\n{AMARILLO}ESTA iba sin transacción porque añade un "
                      f"valor a un enumerado, así que PUEDE haber quedado a "
                      f"medias.{FIN}")
                print(f"{AMARILLO}Revísela antes de volver a ejecutar.{FIN}")
            else:
                print(f"\n{GRIS}Esa migración se deshizo entera; las anteriores "
                      f"quedaron aplicadas.{FIN}")
                print(f"{GRIS}Corrija el archivo y vuelva a ejecutar: continúa "
                      f"desde donde se quedó.{FIN}")
            return 1
        print(f"{VERDE}✓{FIN}"
              + (f" {GRIS}(sin transacción: añade valores a un enumerado){FIN}"
                 if suelta else ""))

    print(f"\n{VERDE}Listo: {len(pendientes)} migración(es) aplicadas.{FIN}")
    print(f"{GRIS}Compruebe con: python scripts/verificar.py{FIN}")
    return 0


async def _con_cierre(aplicar, marcar_hasta) -> int:
    from app.db import cerrar_pool
    try:
        return await principal(aplicar, marcar_hasta)
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aplicar", action="store_true",
                   help="Aplicar de verdad. Sin esto solo dice qué falta.")
    p.add_argument("--marcar-hasta", default=None, metavar="NNNN",
                   help="Anotar como aplicadas, SIN ejecutarlas, las migraciones "
                        "hasta ese número. Para adoptar una base que ya está al día.")
    a = _cli.analizar(p)
    raise SystemExit(asyncio.run(_con_cierre(a.aplicar, a.marcar_hasta)))
