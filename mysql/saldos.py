"""Recalcular, regenerar o fijar saldos de vacaciones desde la terminal.

En PostgreSQL esto se hacía desde DBeaver con `select recalcular_saldos()`.
En MySQL esas reglas viven en el backend (servidor/app/reglas), así que se
llaman desde aquí, con la misma conexión que usa el sistema (servidor/.env):

    .venv/bin/python mysql/saldos.py explicar   --cedula 1712345678
    .venv/bin/python mysql/saldos.py recalcular                   # toda la planilla
    .venv/bin/python mysql/saldos.py recalcular --cedula 1712345678
    .venv/bin/python mysql/saldos.py regenerar  --cedula 1712345678
    .venv/bin/python mysql/saldos.py cargar     --cedula 1712345678 --saldo 8.75 [--fds 0]

`regenerar` y `cargar` cambian días de una persona. Sin `--aplicar` hacen el
cambio dentro de una transacción, muestran cómo quedaría y lo deshacen:
primero se mira, después se aplica.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "servidor"))

from app.db import cerrar_pool, obtener_uno, transaccion  # noqa: E402
from app.reglas import periodos  # noqa: E402
from app.reglas.saldo import explicar_saldo  # noqa: E402


class _Deshacer(Exception):
    """Para salir de la transacción sin confirmarla."""


async def _persona(cedula: str) -> dict:
    fila = await obtener_uno(
        "SELECT id, cedula, nombre, fecha_ingreso, dias_vacaciones, activo FROM users WHERE cedula = %s",
        (cedula,))
    if fila is None:
        raise SystemExit(f"No hay nadie con la cédula {cedula}.")
    return fila


async def _mostrar(user_id) -> None:
    detalle = await explicar_saldo(user_id)
    print(f"  Saldo: {detalle['saldo_total']} días")
    for p in detalle["periodos"]:
        print(f"    período {p['periodo']} ({p['desde']} a {p['hasta']}): asignados {p['asignados']}, "
              f"gozados {p['consumidos']}, saldo {p['saldo']}"
              + (" — caducado" if p["caducado"] else "")
              + ("" if p["devengado"] else " — en curso"))


async def principal(args) -> int:
    try:
        if args.orden == "explicar":
            p = await _persona(args.cedula)
            print(f"{p['nombre']} ({p['cedula']}), ingreso {p['fecha_ingreso']}")
            await _mostrar(p["id"])
            return 0

        if args.orden == "recalcular":
            user_id = (await _persona(args.cedula))["id"] if args.cedula else None
            antes = await obtener_uno("SELECT ROUND(COALESCE(SUM(dias_vacaciones),0),2) AS t FROM users WHERE activo")
            n = await periodos.recalcular_saldos(user_id)
            despues = await obtener_uno("SELECT ROUND(COALESCE(SUM(dias_vacaciones),0),2) AS t FROM users WHERE activo")
            print(f"Recalculadas {n} persona(s). Saldo total de la planilla: {antes['t']} → {despues['t']}")
            if antes["t"] != despues["t"]:
                print("Los totales no coinciden: algo estaba descuadrado. Revise 1.5 de "
                      "mysql/depuracion/01_revisar.sql.")
            return 0

        p = await _persona(args.cedula)
        print(f"{p['nombre']} ({p['cedula']}) — antes:")
        await _mostrar(p["id"])
        try:
            async with transaccion():
                if args.orden == "regenerar":
                    await periodos.generar_periodos_vacaciones(p["id"])
                else:
                    await periodos.cargar_saldo_inicial(p["id"], Decimal(args.saldo), args.fds)
                print("después:")
                await _mostrar(p["id"])
                if not args.aplicar:
                    raise _Deshacer
        except _Deshacer:
            print("\nNO SE GUARDÓ: es solo la vista previa. Repita con --aplicar para hacerlo.")
            return 0
        print("\nGuardado.")
        return 0
    finally:
        await cerrar_pool()


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ordenes = parser.add_subparsers(dest="orden", required=True)
    o = ordenes.add_parser("explicar", help="cómo se llega al saldo de una persona")
    o.add_argument("--cedula", required=True)
    o = ordenes.add_parser("recalcular", help="vuelve a sumar los períodos (no cambia días)")
    o.add_argument("--cedula")
    o = ordenes.add_parser("regenerar", help="crea los períodos que falten tras cambiar la fecha de ingreso")
    o.add_argument("--cedula", required=True)
    o.add_argument("--aplicar", action="store_true")
    o = ordenes.add_parser("cargar", help="fija el saldo real y reparte lo gozado en los períodos antiguos")
    o.add_argument("--cedula", required=True)
    o.add_argument("--saldo", required=True)
    o.add_argument("--fds", type=int, default=0, help="fines de semana obligatorios ya gozados")
    o.add_argument("--aplicar", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(principal(_argumentos())))
