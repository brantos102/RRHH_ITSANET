"""Límites del acceso por código: reemplaza a codigos_sin_usar."""
from __future__ import annotations

from ..db import obtener_uno


async def codigos_sin_usar(cedula: str, ip: str | None) -> dict[str, int]:
    """Códigos pedidos en la última hora y no usados desde el último ingreso.

    Se cuenta desde el último ingreso y no desde hace una hora: un código que
    se pidió y se usó es un ingreso normal, no un intento. Lo que se frena es
    pedir códigos una y otra vez sin usar ninguno, que es la forma del abuso.
    """
    fila = await obtener_uno(
        """SELECT
             COALESCE(SUM(o.cedula = %(cedula)s AND o.consumido_en IS NULL
                          AND o.created_at > COALESCE(
                                (SELECT MAX(consumido_en) FROM auth_otp
                                  WHERE cedula = %(cedula)s AND consumido_en IS NOT NULL),
                                '1000-01-01')), 0) AS por_cedula,
             COALESCE(SUM(%(ip)s IS NOT NULL AND o.ip = %(ip)s AND o.consumido_en IS NULL
                          AND o.created_at > COALESCE(
                                (SELECT MAX(consumido_en) FROM auth_otp
                                  WHERE %(ip)s IS NOT NULL AND ip = %(ip)s AND consumido_en IS NOT NULL),
                                '1000-01-01')), 0) AS por_ip
           FROM auth_otp o
          WHERE o.created_at > NOW(6) - INTERVAL 1 HOUR""",
        {"cedula": cedula, "ip": ip})
    return {"por_cedula": int(fila["por_cedula"]), "por_ip": int(fila["por_ip"])}
