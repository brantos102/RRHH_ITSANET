"""Quién tiene un correo, una cédula o un nombre parecido. Solo consulta.

Nació de un caso real: Talento Humano intenta corregirle el correo a un
colaborador y el sistema responde «El registro ya existe». La ficha con la
que choca no está en la pantalla —puede ser de otra área, o estar inactiva, y
las inactivas no salen en la lista—, así que no hay forma de saber cuál es.

    python scripts/quien_tiene_el_correo.py jganchoso@itsanet.com
    python scripts/quien_tiene_el_correo.py 1316370988
    python scripts/quien_tiene_el_correo.py "ganchozo"

NO MODIFICA NADA. Es una consulta de lectura, pensada para ejecutarse con la
pantalla del error todavía abierta.

El correo se compara ignorando mayúsculas porque la columna es `citext`:
para el sistema, `JGanchoso@...` y `jganchoso@...` son el mismo correo, y
buscar distinguiendo mayúsculas diría que no existe cuando sí existe.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def _pintar(f: dict) -> None:
    estado = f"{VERDE}activo{FIN}" if f["activo"] else f"{ROJO}INACTIVO{FIN}"
    print(f"\n  {f['nombre']}  [{estado}]")
    print(f"    cédula ........ {f['cedula']}")
    print(f"    correo ........ {f['email'] or GRIS + '(sin correo)' + FIN}"
          + (f"  {AMARILLO}(marcado como pendiente de completar){FIN}"
             if f["correo_pendiente"] else ""))
    print(f"    cargo ......... {f['cargo'] or '—'}")
    print(f"    área .......... {f['departamento'] or '—'}")
    print(f"    ingreso ....... {f['fecha_ingreso']}")
    print(f"    jefe .......... {f['jefe'] or GRIS + 'sin jefe asignado' + FIN}")


async def principal(texto: str) -> int:
    from app.db import obtener_todos

    campos = """u.cedula, u.nombre, u.email, u.correo_pendiente, u.cargo,
                u.departamento, u.fecha_ingreso, u.activo,
                (select j.nombre from public.users j where j.id = u.jefe_id) as jefe"""

    # El correo, exacto e ignorando mayúsculas: es el choque que se busca.
    exactas = await obtener_todos(
        f"select {campos} from public.users u where u.email = %s", (texto,))
    if exactas:
        print(f"\n{AMARILLO}El correo «{texto}» YA ESTÁ en esta ficha:{FIN}")
        for f in exactas:
            _pintar(f)
        print(f"\n{GRIS}Un correo no puede estar en dos fichas: el código de acceso "
              f"de una persona llegaría al buzón de otra.{FIN}")
        print(f"{GRIS}Deje primero en blanco el correo de esta ficha, o corríjalo, "
              f"y después asígnelo a quien corresponde.{FIN}")
        return 0

    # La cédula.
    por_cedula = await obtener_todos(
        f"select {campos} from public.users u where u.cedula = %s", (texto,))
    if por_cedula:
        print(f"\n{VERDE}Ficha con cédula {texto}:{FIN}")
        for f in por_cedula:
            _pintar(f)
        return 0

    # Lo que se le parezca: nombre o correo.
    parecidas = await obtener_todos(
        f"""select {campos} from public.users u
             where u.nombre ilike %(t)s or u.email::text ilike %(t)s
             order by u.activo desc, u.nombre limit 20""",
        {"t": f"%{texto}%"})
    if parecidas:
        print(f"\n{GRIS}Nadie tiene exactamente «{texto}». Se le parecen:{FIN}")
        for f in parecidas:
            _pintar(f)
        return 0

    print(f"\n{GRIS}Nadie tiene «{texto}», ni nada que se le parezca.{FIN}")
    print(f"{GRIS}Si el error decía que ya existe, el choque es por otro campo: "
          f"vuelva a intentarlo y lea el mensaje completo.{FIN}")
    return 0


async def _con_cierre(texto) -> int:
    from app.db import cerrar_pool
    try:
        return await principal(texto)
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("texto", help="Un correo, una cédula o parte de un nombre")
    a = _cli.analizar(p)
    raise SystemExit(asyncio.run(_con_cierre(a.texto.strip())))
