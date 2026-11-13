"""La pantalla principal: qué bloques ve cada quien y cómo se configuran.

Reemplaza a panel_de y panel_configurar.

El filtrado por rol se hace aquí y viaja ya filtrado: mandar la lista entera
con un «no mires estos» es esconder algo donde cualquiera lo encuentra
abriendo las herramientas del navegador.
"""
from __future__ import annotations

from typing import Any

from ..db import a_json, ejecutar, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio


async def panel_de(user_id) -> list[dict[str, Any]]:
    """Los bloques que esta persona debe ver, ya filtrados por rol."""
    return await obtener_todos(
        """SELECT b.clave, b.titulo, b.orden, b.cuerpo
             FROM panel_bloques b
             JOIN users u ON u.id = %s
            WHERE b.visible
              AND (JSON_LENGTH(b.roles) = 0 OR JSON_CONTAINS(b.roles, JSON_QUOTE(u.rol)))
              -- Un aviso sin texto no es un aviso: es un recuadro vacío.
              AND (b.clave <> 'anuncio' OR NULLIF(TRIM(COALESCE(b.cuerpo, '')), '') IS NOT NULL)
            ORDER BY b.orden, b.clave""", (user_id,))


async def panel_configurar(clave: str, por, visible: bool | None = None, orden: int | None = None,
                           roles: list[str] | None = None, cuerpo: str | None = None) -> dict[str, Any]:
    """Cambia un bloque. Rechaza ocultar los esenciales."""
    async with transaccion():
        bloque = await obtener_uno("SELECT * FROM panel_bloques WHERE clave = %s FOR UPDATE", (clave,))
        if bloque is None:
            raise ReglaDeNegocio(f"No existe el bloque «{clave}» en la pantalla principal")
        if visible is False and bloque["esencial"]:
            raise ReglaDeNegocio(f"«{bloque['titulo']}» no se puede ocultar: es lo que la gente viene "
                                 "a ver. Puede moverlo de sitio, no apagarlo.")
        await ejecutar(
            """UPDATE panel_bloques
                  SET visible = COALESCE(%s, visible),
                      orden = COALESCE(%s, orden),
                      roles = COALESCE(CAST(%s AS JSON), roles),
                      -- El cuerpo se limpia a vacío para poder borrarlo: un
                      -- COALESCE puro dejaría el aviso viejo colgado para siempre.
                      cuerpo = CASE WHEN %s IS NULL THEN cuerpo ELSE NULLIF(TRIM(%s), '') END,
                      actualizado_en = NOW(6),
                      actualizado_por = %s
                WHERE clave = %s""",
            (visible, orden, None if roles is None else a_json(roles), cuerpo, cuerpo, por, clave))
        return await obtener_uno("SELECT * FROM panel_bloques WHERE clave = %s", (clave,))
