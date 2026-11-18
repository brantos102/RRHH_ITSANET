"""Jefe alterno: quién decide una solicitud cuando el jefe directo no puede.

El jefe directo puede no tener correo registrado (no le llega el aviso),
estar de vacaciones o con un permiso de día completo hoy, o no existir en
la ficha. En esos casos el colaborador puede elegir, SOLO para esa
solicitud, a otra jefatura. El jefe de la ficha no cambia: la solicitud
guarda quién era (jefe_original_id) y por qué se usó otro.
"""
from __future__ import annotations

from typing import Any

from ..db import obtener_todos, obtener_uno


async def ausencia_hoy(user_id) -> dict[str, Any] | None:
    """La vacación o el permiso de día completo aprobado que cubre hoy."""
    if not user_id:
        return None
    return await obtener_uno(
        """SELECT r.tipo, r.fecha_inicio, r.fecha_fin
             FROM requests r
            WHERE r.user_id = %s AND r.estado IN ('aprobado', 'pendiente_anulacion')
              AND r.eliminada_en IS NULL AND r.hora_inicio IS NULL
              AND CURRENT_DATE() BETWEEN r.fecha_inicio AND r.fecha_fin
            ORDER BY r.fecha_fin DESC LIMIT 1""", (str(user_id),))


async def situacion(solicitud: dict) -> dict[str, Any] | None:
    """Por qué el jefe de esta solicitud no puede atenderla, o None si puede.

    Solo aplica mientras espera al jefe."""
    if solicitud.get("estado") != "pendiente_jefe":
        return None
    jefe_id = solicitud.get("jefe_id")
    if not jefe_id:
        return {"motivo": "sin_jefe", "texto": "No tiene jefe directo registrado."}
    jefe = await obtener_uno("SELECT id, nombre, email, activo FROM users WHERE id = %s", (str(jefe_id),))
    if jefe is None or not jefe["activo"]:
        return {"motivo": "jefe_inactivo", "jefe": jefe and jefe["nombre"],
                "texto": "Su jefe directo ya no está activo en el sistema."}
    ausente = await ausencia_hoy(jefe_id)
    if ausente:
        que = "de vacaciones" if ausente["tipo"] == "vacacion" else "con permiso"
        return {"motivo": "ausente", "jefe": jefe["nombre"], "hasta": ausente["fecha_fin"],
                "texto": f"{jefe['nombre']} está {que} hasta el {ausente['fecha_fin']:%d/%m/%Y}."}
    if not jefe["email"]:
        return {"motivo": "sin_correo", "jefe": jefe["nombre"],
                "texto": f"{jefe['nombre']} no tiene correo registrado: el aviso no le llega por correo."}
    return None


async def candidatos(solicitud: dict) -> list[dict[str, Any]]:
    """Quiénes pueden decidir como jefe alterno: jefaturas, Talento Humano y
    administración activos, con correo, que no estén ausentes hoy. Primero
    el jefe del jefe y las jefaturas del mismo departamento."""
    filas = await obtener_todos(
        """SELECT u.id, u.nombre, u.cargo, u.departamento, u.rol,
                  (u.id = (SELECT j.jefe_id FROM users j WHERE j.id = %(jefe)s)) AS es_superior,
                  (u.departamento IS NOT NULL AND u.departamento =
                     (SELECT s.departamento FROM users s WHERE s.id = %(yo)s)) AS mismo_departamento
             FROM users u
            WHERE u.activo AND u.rol IN ('jefe', 'rrhh', 'admin')
              AND u.email IS NOT NULL
              AND u.id <> %(yo)s AND (%(jefe)s IS NULL OR u.id <> %(jefe)s)
              AND NOT EXISTS (
                    SELECT 1 FROM requests r
                     WHERE r.user_id = u.id AND r.estado IN ('aprobado', 'pendiente_anulacion')
                       AND r.eliminada_en IS NULL AND r.hora_inicio IS NULL
                       AND CURRENT_DATE() BETWEEN r.fecha_inicio AND r.fecha_fin)
            ORDER BY es_superior DESC, mismo_departamento DESC, (u.rol = 'jefe') DESC, u.nombre
            LIMIT 300""",
        {"yo": str(solicitud["user_id"]),
         "jefe": str(solicitud["jefe_id"]) if solicitud.get("jefe_id") else None})
    return [{"id": str(f["id"]), "nombre": f["nombre"], "cargo": f["cargo"], "departamento": f["departamento"],
             "rol": f["rol"], "sugerido": bool(f["es_superior"] or f["mismo_departamento"])} for f in filas]
