"""Lo que hace administración sobre las personas: bajas, jefaturas, el equipo
de Talento Humano y los lineamientos del formulario.

Reemplaza a dar_de_baja, jefatura_crear, jefatura_quitar, rrhh_integrar,
rrhh_retirar y lineamiento_guardar. Cada una corre en una transacción y lee
la ficha con FOR UPDATE: dos administradores que tocan a la misma persona a
la vez no se pisan.
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..db import ejecutar, insertar, obtener_uno, transaccion
from ..errores import ReglaDeNegocio


def _limpio(texto) -> str:
    """btrim de PostgreSQL: recorta solo espacios."""
    return str(texto if texto is not None else "").strip(" ")


def _dos_decimales(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _persona(user_id) -> dict[str, Any]:
    fila = await obtener_uno("SELECT * FROM users WHERE id = %s FOR UPDATE", (str(user_id),))
    if fila is None:
        raise ReglaDeNegocio("No se encontró a esa persona.")
    return fila


async def dar_de_baja(persona_id, fecha: dt.date, motivo: str | None, detalle: str | None,
                      actor) -> dict[str, Any]:
    """Cierra la ficha y devuelve lo que queda abierto a su nombre."""
    async with transaccion():
        persona = await _persona(persona_id)
        if str(persona_id) == str(actor):
            raise ReglaDeNegocio("No puede darse de baja usted mismo. Pídaselo a otro administrador.")
        if motivo is None:
            raise ReglaDeNegocio("Indique cómo terminó la relación laboral: es lo primero que se "
                                 "pregunta al revisar un expediente.")
        hoy = (await obtener_uno("SELECT CURRENT_DATE() AS d"))["d"]
        if fecha > hoy + dt.timedelta(days=1):
            raise ReglaDeNegocio("La fecha de salida no puede ser futura.")

        # Lo que queda abierto no impide la baja —la persona ya se fue—, pero
        # se devuelve para que Talento Humano lo resuelva.
        a_cargo = (await obtener_uno(
            "SELECT COUNT(*) AS n FROM users WHERE jefe_id = %s AND activo", (str(persona_id),)))["n"]
        pendientes = (await obtener_uno(
            """SELECT COUNT(*) AS n FROM requests
                WHERE user_id = %s AND estado IN ('pendiente_jefe', 'pendiente_rrhh')""",
            (str(persona_id),)))["n"]
        saldo = (await obtener_uno(
            "SELECT COALESCE(SUM(dias_saldo), 0) AS s FROM vacation_periods "
            "WHERE user_id = %s AND NOT caducado", (str(persona_id),)))["s"]

        await ejecutar(
            """UPDATE users
                  SET activo = FALSE, fecha_salida = %s, motivo_salida = %s,
                      detalle_salida = %s, salida_registrada_por = %s, salida_registrada_en = NOW(6)
                WHERE id = %s""",
            (fecha, motivo, _limpio(detalle) or None, str(actor), str(persona_id)))

    por_liquidar = _dos_decimales(saldo)
    return {
        "id": str(persona_id), "nombre": persona["nombre"], "motivo": motivo,
        "fecha_salida": fecha.isoformat(),
        "personas_a_cargo": int(a_cargo), "solicitudes_pendientes": int(pendientes),
        "dias_por_liquidar": float(por_liquidar),
        "mensaje": f"{persona['nombre']} queda dado de baja el {fecha:%d/%m/%Y}. Las vacaciones no "
                   f"gozadas se pagan (Art. 76): {por_liquidar} día(s) por liquidar.",
    }


async def jefatura_crear(persona_id, actor) -> dict[str, Any]:
    async with transaccion():
        persona = await _persona(persona_id)
        if not persona["activo"]:
            raise ReglaDeNegocio(f"La ficha de {persona['nombre']} está inactiva: primero reactívela.")
        # Talento Humano y administración ya aprueban por su rol: nombrarlos
        # «jefe» les quitaría atribuciones en vez de dárselas.
        if persona["rol"] in ("rrhh", "admin"):
            return {"id": str(persona_id), "nombre": persona["nombre"], "cambio": False,
                    "mensaje": f"{persona['nombre']} ya aprueba por su rol de {persona['rol']}. "
                               "No hace falta nombrarlo jefe."}
        if persona["rol"] == "jefe":
            return {"id": str(persona_id), "nombre": persona["nombre"], "cambio": False,
                    "mensaje": f"{persona['nombre']} ya es jefatura."}
        await ejecutar("UPDATE users SET rol = 'jefe' WHERE id = %s", (str(persona_id),))
    return {"id": str(persona_id), "nombre": persona["nombre"], "cambio": True,
            "rol_anterior": persona["rol"],
            "mensaje": f"{persona['nombre']} queda como jefatura. Asígnele su gente desde la "
                       "ficha de cada uno."}


async def jefatura_quitar(jefe_id, nuevo_jefe_id, rol_destino: str | None, actor) -> dict[str, Any]:
    destino = rol_destino or "empleado"
    async with transaccion():
        jefe = await _persona(jefe_id)
        if str(jefe_id) == str(actor):
            raise ReglaDeNegocio("No puede quitarse su propia jefatura. Pídaselo a otro administrador.")
        if destino == "jefe":
            raise ReglaDeNegocio("El rol de destino no puede seguir siendo jefe: eso no quita nada.")

        a_cargo = (await obtener_uno(
            "SELECT COUNT(*) AS n FROM users WHERE jefe_id = %s AND activo", (str(jefe_id),)))["n"]
        if a_cargo > 0 and nuevo_jefe_id is None:
            raise ReglaDeNegocio(f"{jefe['nombre']} tiene {a_cargo} persona(s) a cargo. Indique a qué "
                                 "jefatura pasan antes de quitarle el mando.")

        nuevo, movidos, pendientes = None, 0, 0
        if nuevo_jefe_id is not None:
            if str(nuevo_jefe_id) == str(jefe_id):
                raise ReglaDeNegocio("La jefatura de destino no puede ser la misma que se está quitando.")
            nuevo = await obtener_uno("SELECT * FROM users WHERE id = %s FOR UPDATE", (str(nuevo_jefe_id),))
            if nuevo is None or not nuevo["activo"]:
                raise ReglaDeNegocio("La jefatura de destino no existe o está inactiva.")
            if nuevo["rol"] not in ("jefe", "rrhh", "admin"):
                raise ReglaDeNegocio(f"{nuevo['nombre']} no puede recibir gente a cargo: no es jefatura.")

            # Si el receptor le reportaba a quien pierde el mando, no puede
            # quedar reportándose a sí mismo: hereda el jefe de su antiguo superior.
            if nuevo["jefe_id"] is not None and str(nuevo["jefe_id"]) == str(jefe_id):
                heredado = jefe["jefe_id"]
                if heredado is not None and str(heredado) == str(nuevo_jefe_id):
                    heredado = None
                await ejecutar("UPDATE users SET jefe_id = %s WHERE id = %s",
                               (heredado, str(nuevo_jefe_id)))

            movidos = await ejecutar("UPDATE users SET jefe_id = %s WHERE jefe_id = %s AND id <> %s",
                                     (str(nuevo_jefe_id), str(jefe_id), str(nuevo_jefe_id)))
            # Lo que esperaba su firma pasa con la gente: si no, la solicitud
            # queda «pendiente del jefe» para siempre.
            pendientes = await ejecutar(
                "UPDATE requests SET jefe_id = %s WHERE jefe_id = %s AND estado = 'pendiente_jefe'",
                (str(nuevo_jefe_id), str(jefe_id)))

        await ejecutar("UPDATE users SET rol = %s WHERE id = %s", (destino, str(jefe_id)))

    return {
        "id": str(jefe_id), "nombre": jefe["nombre"], "rol_anterior": jefe["rol"], "rol_nuevo": destino,
        "nuevo_jefe": str(nuevo_jefe_id) if nuevo_jefe_id else None,
        "nuevo_jefe_nombre": nuevo["nombre"] if nuevo else None,
        "personas_movidas": movidos, "solicitudes_movidas": pendientes,
        "mensaje": (f"{jefe['nombre']} deja de ser jefatura. No tenía gente a cargo."
                    if nuevo_jefe_id is None else
                    f"{jefe['nombre']} deja de ser jefatura. {movidos} persona(s) y {pendientes} "
                    f"solicitud(es) pendiente(s) pasaron a {nuevo['nombre']}."),
    }


async def rrhh_integrar(persona_id, region: str | None, actor) -> dict[str, Any]:
    region = _limpio(region) or "sierra"
    async with transaccion():
        persona = await _persona(persona_id)
        if not persona["activo"]:
            raise ReglaDeNegocio(f"La ficha de {persona['nombre']} está inactiva: primero reactívela.")
        if await obtener_uno("SELECT 1 AS x FROM regiones WHERE codigo = %s", (region,)) is None:
            raise ReglaDeNegocio(f"La región «{region}» no existe.")
        if persona["rol"] == "admin":
            # Bajar a un administrador a rrhh le quitaría atribuciones sin avisar.
            await ejecutar("UPDATE users SET region = %s WHERE id = %s", (region, str(persona_id)))
            return {"id": str(persona_id), "nombre": persona["nombre"], "cambio": True, "rol": "admin",
                    "mensaje": f"{persona['nombre']} es administrador del sistema y ya ve todo. "
                               f"Se le asignó la región {region}."}
        await ejecutar("UPDATE users SET rol = 'rrhh', region = %s WHERE id = %s",
                       (region, str(persona_id)))
    return {"id": str(persona_id), "nombre": persona["nombre"], "cambio": persona["rol"] != "rrhh",
            "rol": "rrhh", "region": region,
            "mensaje": f"{persona['nombre']} integra Talento Humano en la región {region}."}


async def rrhh_retirar(persona_id, rol_destino: str | None, actor) -> dict[str, Any]:
    destino = rol_destino or "empleado"
    async with transaccion():
        persona = await _persona(persona_id)
        if str(persona_id) == str(actor):
            raise ReglaDeNegocio("No puede retirarse usted mismo del departamento. "
                                 "Pídaselo a otro administrador.")
        if destino in ("rrhh", "admin"):
            raise ReglaDeNegocio("El rol de destino seguiría viendo los expedientes: eso no retira a nadie.")
        region = persona["region"] or "sierra"
        # Una región sin nadie deja sus solicitudes sin quien las resuelva.
        quedan = (await obtener_uno(
            """SELECT COUNT(*) AS n FROM v_talento_humano
                WHERE region = %s AND id <> %s AND activo""", (region, str(persona_id))))["n"]
        if quedan == 0:
            raise ReglaDeNegocio(f"Es la única persona de Talento Humano en la región {region}. "
                                 "Integre a alguien más antes de retirarla, o sus solicitudes no "
                                 "le llegarán a nadie.")
        await ejecutar("UPDATE users SET rol = %s WHERE id = %s", (destino, str(persona_id)))
    return {"id": str(persona_id), "nombre": persona["nombre"], "rol_anterior": persona["rol"],
            "rol_nuevo": destino, "quedan_en_la_region": int(quedan),
            "mensaje": f"{persona['nombre']} deja Talento Humano. Quedan {quedan} persona(s) en la "
                       f"región {region}."}


async def lineamiento_guardar(lineamiento_id: int | None, por, texto: str | None = None,
                              ambito: str | None = None, orden: int | None = None,
                              activo: bool | None = None) -> dict[str, Any]:
    """Crea (sin id) o cambia un lineamiento del formulario de solicitud."""
    async with transaccion():
        if lineamiento_id is None:
            if texto is None or len(_limpio(texto)) < 5:
                raise ReglaDeNegocio("Escriba el lineamiento: al menos cinco caracteres")
            nuevo = await insertar(
                """INSERT INTO lineamientos_solicitud (ambito, texto, orden, actualizado_en, actualizado_por)
                   VALUES (%s, %s, %s, NOW(6), %s)""",
                (ambito or "ambos", _limpio(texto), 100 if orden is None else orden, str(por)))
            return await obtener_uno("SELECT * FROM lineamientos_solicitud WHERE id = %s", (nuevo,))

        if await obtener_uno("SELECT 1 AS x FROM lineamientos_solicitud WHERE id = %s FOR UPDATE",
                             (lineamiento_id,)) is None:
            raise ReglaDeNegocio("Ese lineamiento ya no existe")
        await ejecutar(
            """UPDATE lineamientos_solicitud
                  SET texto = COALESCE(NULLIF(%s, ''), texto),
                      ambito = COALESCE(%s, ambito),
                      orden = COALESCE(%s, orden),
                      activo = COALESCE(%s, activo),
                      actualizado_en = NOW(6),
                      actualizado_por = %s
                WHERE id = %s""",
            (None if texto is None else _limpio(texto), ambito, orden, activo, str(por), lineamiento_id))
        return await obtener_uno("SELECT * FROM lineamientos_solicitud WHERE id = %s", (lineamiento_id,))
