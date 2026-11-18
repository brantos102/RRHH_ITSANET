"""Garita: el regreso de quien salió con un permiso aprobado.

Reemplaza a registrar_retorno.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..db import ZONA_ECUADOR, ejecutar, obtener_uno, transaccion
from ..errores import ReglaDeNegocio


def _hora(valor) -> dt.time | None:
    if valor is None or isinstance(valor, dt.time):
        return valor
    return (dt.datetime.min + valor).time()


async def registrar_retorno(request_id, guardia_id, ip: str | None, agente: str | None) -> dict[str, Any]:
    """Anota el regreso y cuánto se pasó de la hora o del día esperado."""
    async with transaccion():
        quien = await obtener_uno("SELECT rol FROM users WHERE id = %s", (guardia_id,))
        # Más estricta que la original: en PostgreSQL, un guardia inexistente
        # dejaba el rol en NULL y la comprobación no lo detenía.
        if quien is None or quien["rol"] not in ("guardia", "rrhh", "admin"):
            raise ReglaDeNegocio("Solo garita o Talento Humano registran el retorno")

        sol = await obtener_uno("SELECT * FROM requests WHERE id = %s FOR UPDATE", (request_id,))
        if sol is None:
            raise ReglaDeNegocio("La solicitud no existe")
        if sol["estado"] != "aprobado":
            raise ReglaDeNegocio(f"La solicitud no está aprobada (está en {sol['estado']})")

        # Sin salida previa no hay retorno: sería anotar que volvió alguien
        # que nunca se fue.
        salida = await obtener_uno(
            """SELECT created_at FROM access_logs
                WHERE request_id = %s AND tipo_acceso = 'salida_empleado' AND autorizado
                ORDER BY created_at LIMIT 1""", (request_id,))
        if salida is None:
            raise ReglaDeNegocio("No hay salida registrada para esta autorización: "
                                 "primero se registra la salida")
        if sol["retorno_en"] is not None:
            raise ReglaDeNegocio(f"El retorno ya quedó registrado el {sol['retorno_en']:%d/%m/%Y %H:%M}")

        persona = await obtener_uno("SELECT nombre, cedula FROM users WHERE id = %s", (sol["user_id"],))
        ahora = (await obtener_uno("SELECT NOW(6) AS t"))["t"]
        hora_fin = _hora(sol["hora_fin"])
        por_horas = hora_fin is not None and sol["fecha_inicio"] == sol["fecha_fin"]

        if por_horas:
            esperado = dt.datetime.combine(sol["fecha_fin"], hora_fin, tzinfo=ZONA_ECUADOR)
            minutos = Decimal(str((ahora - esperado).total_seconds())) / 60
            # Volver antes de la hora no es un exceso de nada.
            exceso_min = max(int(minutos.quantize(Decimal(1), ROUND_HALF_UP)), 0)
            exceso_dias = None
        else:
            # Se esperaba de vuelta el día siguiente al último de ausencia.
            siguiente = sol["fecha_fin"] + dt.timedelta(days=1)
            esperado = dt.datetime.combine(siguiente, dt.time(0), tzinfo=ZONA_ECUADOR)
            exceso_min = None
            exceso_dias = max((ahora.date() - siguiente).days, 0)

        await ejecutar(
            """UPDATE requests
                  SET retorno_en = %s, retorno_exceso_minutos = %s, retorno_exceso_dias = %s,
                      retorno_guardia = %s
                WHERE id = %s""",
            (ahora, exceso_min, exceso_dias, guardia_id, request_id))
        await ejecutar(
            """INSERT INTO access_logs
                 (user_id, cedula, request_id, tipo_acceso, autorizado, guardia_id, ip, user_agent, metadata)
               VALUES (%s, %s, %s, 'retorno_empleado', TRUE, %s, %s, %s, %s)""",
            (sol["user_id"], persona["cedula"], request_id, guardia_id, ip, agente,
             {"esperado": esperado, "exceso_minutos": exceso_min, "exceso_dias": exceso_dias}))

        return {
            "folio": sol["folio"], "nombre": persona["nombre"], "cedula": persona["cedula"],
            "salio": salida["created_at"], "volvio": ahora, "esperado": esperado,
            "por_horas": por_horas, "exceso_minutos": exceso_min, "exceso_dias": exceso_dias,
            "a_tiempo": (exceso_min or 0) <= 0 and (exceso_dias or 0) == 0,
        }
