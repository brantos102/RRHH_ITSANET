"""Personal temporal: entrada, salida y cierre a mano de una jornada.

Reemplaza a temporal_registrar_entrada, temporal_registrar_salida,
temporal_cerrar_jornada y temporal_semana. Una jornada por operario y día;
sin salida no se puede pagar, y el sistema la señala en vez de inventarla.

Las horas se calculan en la base, con su propio reloj: la entrada la anotó
la base, y restarle la hora del servidor de aplicaciones mezclaría dos relojes.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..db import ejecutar, nuevo_id, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio

_HORAS = "ROUND(TIMESTAMPDIFF(MICROSECOND, entrada_en, {hasta}) / 3600000000, 2)"


def _hhmm(momento) -> str:
    return momento.strftime("%H:%M") if momento else ""


def _limpio(texto) -> str:
    return str(texto if texto is not None else "").strip(" ")


async def _operario(temporal_id) -> dict[str, Any]:
    persona = await obtener_uno("SELECT * FROM personal_temporal WHERE id = %s", (str(temporal_id),))
    if persona is None:
        raise ReglaDeNegocio("Ese operario no está registrado")
    return persona


async def registrar_entrada(temporal_id, por, observacion: str | None = None) -> dict[str, Any]:
    async with transaccion():
        persona = await _operario(temporal_id)
        if not persona["activo"]:
            raise ReglaDeNegocio(f"{persona['nombre']} ya no está activo. Reactívelo antes de "
                                 "registrar su jornada.")
        hoy = await obtener_uno(
            "SELECT * FROM jornadas_temporales WHERE temporal_id = %s AND fecha = CURRENT_DATE() FOR UPDATE",
            (str(temporal_id),))
        if hoy is not None:
            if hoy["salida_en"] is None:
                raise ReglaDeNegocio(f"{persona['nombre']} ya tiene su entrada registrada hoy a las "
                                     f"{_hhmm(hoy['entrada_en'])}. Lo que falta es su salida.")
            raise ReglaDeNegocio(f"{persona['nombre']} ya cumplió su jornada de hoy "
                                 f"({_hhmm(hoy['entrada_en'])} a {_hhmm(hoy['salida_en'])}).")
        jornada_id = nuevo_id()
        await ejecutar(
            """INSERT INTO jornadas_temporales (id, temporal_id, registro_entrada, observacion)
               VALUES (%s, %s, %s, %s)""",
            (jornada_id, str(temporal_id), por, _limpio(observacion) or None))
        jornada = await obtener_uno("SELECT * FROM jornadas_temporales WHERE id = %s", (jornada_id,))
    return {"jornada_id": str(jornada_id), "nombre": persona["nombre"], "labor": persona["labor"],
            "entrada": jornada["entrada_en"], "movimiento": "entrada"}


async def registrar_salida(temporal_id, por, observacion: str | None = None) -> dict[str, Any]:
    async with transaccion():
        persona = await _operario(temporal_id)
        jornada = await obtener_uno(
            "SELECT * FROM jornadas_temporales WHERE temporal_id = %s AND fecha = CURRENT_DATE() FOR UPDATE",
            (str(temporal_id),))
        if jornada is None:
            raise ReglaDeNegocio(f"No hay entrada registrada hoy para {persona['nombre']}. "
                                 "No puede salir quien no entró.")
        if jornada["salida_en"] is not None:
            raise ReglaDeNegocio(f"{persona['nombre']} ya registró su salida hoy a las "
                                 f"{_hhmm(jornada['salida_en'])}.")
        await ejecutar(
            f"""UPDATE jornadas_temporales
                   SET salida_en = NOW(6), horas = {_HORAS.format(hasta='NOW(6)')},
                       registro_salida = %s,
                       observacion = COALESCE(NULLIF(%s, ''), observacion)
                 WHERE id = %s""",
            (por, _limpio(observacion), str(jornada["id"])))
        jornada = await obtener_uno("SELECT * FROM jornadas_temporales WHERE id = %s", (str(jornada["id"]),))
    return {"jornada_id": str(jornada["id"]), "nombre": persona["nombre"],
            "entrada": jornada["entrada_en"], "salida": jornada["salida_en"],
            "horas": jornada["horas"], "movimiento": "salida"}


async def cerrar_jornada(jornada_id, salida: dt.datetime, por, motivo: str | None) -> dict[str, Any]:
    """Talento Humano cierra a mano una jornada que quedó sin salida."""
    quien = await obtener_uno("SELECT rol FROM users WHERE id = %s", (str(por),))
    if quien is None or quien["rol"] not in ("rrhh", "admin"):
        raise ReglaDeNegocio("Solo Talento Humano cierra a mano una jornada")
    if len(_limpio(motivo)) < 10:
        raise ReglaDeNegocio("Explique por qué se cierra a mano: queda en la bitácora")
    async with transaccion():
        jornada = await obtener_uno("SELECT * FROM jornadas_temporales WHERE id = %s FOR UPDATE",
                                    (str(jornada_id),))
        if jornada is None:
            raise ReglaDeNegocio("Esa jornada no existe")
        if jornada["salida_en"] is not None:
            raise ReglaDeNegocio("Esa jornada ya está cerrada")
        if (await obtener_uno("SELECT %s < entrada_en AS antes FROM jornadas_temporales WHERE id = %s",
                              (salida, str(jornada_id))))["antes"]:
            raise ReglaDeNegocio("La salida no puede ser anterior a la entrada")
        await ejecutar(
            f"""UPDATE jornadas_temporales
                   SET salida_en = %s, horas = {_HORAS.format(hasta='%s')},
                       registro_salida = %s,
                       observacion = CONCAT(TRIM(COALESCE(CONCAT(observacion, ' · '), '')),
                                            'Cerrada a mano: ', %s)
                 WHERE id = %s""",
            (salida, salida, str(por), _limpio(motivo), str(jornada_id)))
        jornada = await obtener_uno("SELECT * FROM jornadas_temporales WHERE id = %s", (str(jornada_id),))
    return {"jornada_id": str(jornada_id), "horas": jornada["horas"], "salida": jornada["salida_en"]}


async def semana(desde: dt.date | None = None, hasta: dt.date | None = None) -> list[dict[str, Any]]:
    """Jornadas y horas por operario. De lunes a domingo de la semana en
    curso si no se dice otra cosa: es como se liquida."""
    return await obtener_todos(
        """SELECT t.id AS temporal_id, t.cedula, t.nombre, t.labor, t.proveedor,
                  COUNT(j.id) AS jornadas,
                  COALESCE(SUM(j.horas), 0) AS horas,
                  COALESCE(SUM(j.salida_en IS NULL), 0) AS sin_cerrar,
                  MIN(j.fecha) AS primera,
                  MAX(j.fecha) AS ultima
             FROM personal_temporal t
             JOIN jornadas_temporales j ON j.temporal_id = t.id
             CROSS JOIN (SELECT COALESCE(%s, CURRENT_DATE() - INTERVAL WEEKDAY(CURRENT_DATE()) DAY) AS desde,
                                COALESCE(%s, CURRENT_DATE() - INTERVAL WEEKDAY(CURRENT_DATE()) DAY
                                             + INTERVAL 6 DAY) AS hasta) r
            WHERE j.fecha BETWEEN r.desde AND r.hasta
            GROUP BY t.id, t.cedula, t.nombre, t.labor, t.proveedor
            ORDER BY t.nombre""", (desde, hasta))
