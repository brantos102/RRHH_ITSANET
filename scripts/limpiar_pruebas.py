"""Deja la base de pruebas en un estado desde el que las pruebas de navegador
pueden volver a correr.

Por qué hace falta: cada guion de extremo a extremo crea solicitudes en fechas
fijas (la semana del 2 de noviembre, la semana a ocho semanas de hoy). Antes
nada impedía duplicar ausencias, así que repetir una corrida «funcionaba»
dejando solicitudes encimadas. Desde que el sistema rechaza el solape —una
persona no puede estar ausente dos veces los mismos días— la segunda corrida
choca con lo que dejó la primera. No es un defecto de la regla: los guiones
nunca fueron repetibles, solo lo parecían.

Toca únicamente al personal de prueba —el de correo `@itsanet.test`— y jamás a
la planilla real. Cancela sus solicitudes vivas; no borra nada.

    python scripts/limpiar_pruebas.py            # dice qué haría
    python scripts/limpiar_pruebas.py --aplicar  # lo hace
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import cerrar_pool, obtener_todos, obtener_uno  # noqa: E402

DOMINIO_DE_PRUEBA = "@itsanet.test"

SQL_VIVAS = """
    select r.id, r.folio, r.estado, r.fecha_inicio, r.fecha_fin, u.nombre, u.email
    from public.requests r
    join public.users u on u.id = r.user_id
    where u.email like %s
      and r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado')
      -- Solo lo que todavía puede estorbar. Una ausencia ya terminada no se
      -- cruza con nada que se cree hoy, y entre ellas están las del `seed`,
      -- que conviene no tocar: alguna prueba se apoya en ellas.
      and r.fecha_fin >= current_date
    order by u.nombre, r.fecha_inicio
"""


async def principal(aplicar: bool) -> int:
    ajustes = get_settings()
    if ajustes.es_produccion:
        print("Esto no se ejecuta en producción. ENTORNO=%s" % ajustes.entorno)
        return 2

    vivas = await obtener_todos(SQL_VIVAS, (f"%{DOMINIO_DE_PRUEBA}",))
    if not vivas:
        print(f"No hay solicitudes vivas del personal {DOMINIO_DE_PRUEBA}. Nada que hacer.")
        return 0

    print(f"Solicitudes vivas del personal de prueba ({len(vivas)}):")
    for v in vivas:
        print(f"  Nº {v['folio']:<6} {v['estado']:<20} {v['fecha_inicio']} → {v['fecha_fin']}"
              f"   {v['nombre']}")

    if not aplicar:
        print("\nNada cambió. Repita con --aplicar para cancelarlas.")
        return 0

    # Una por una y no en bloque: cada cancelación dispara la devolución de
    # saldo y de fines de semana, y conviene que un fallo diga en cuál fue.
    canceladas = 0
    for v in vivas:
        try:
            await obtener_uno(
                "update public.requests set estado = 'cancelado' where id = %s returning id",
                (v["id"],),
            )
            canceladas += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ Nº {v['folio']}: {exc}")

    print(f"\nCanceladas {canceladas} de {len(vivas)}. Las pruebas de navegador ya pueden correr.")
    return 0 if canceladas == len(vivas) else 1


async def _con_cierre(aplicar: bool) -> int:
    """El pool se cierra dentro del mismo bucle que lo abrió.

    Cerrarlo en un `asyncio.run` aparte dejaba un «Event loop is closed» al
    final de cada ejecución: el pool pertenece al bucle donde nació.
    """
    try:
        return await principal(aplicar)
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aplicar", action="store_true",
                   help="Cancelar de verdad (sin esto solo muestra).")
    argumentos = p.parse_args()
    raise SystemExit(asyncio.run(_con_cierre(argumentos.aplicar)))
