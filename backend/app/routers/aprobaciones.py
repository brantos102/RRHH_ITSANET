"""Flujo de aprobación: jefe inmediato, luego Talento Humano, luego QR.

Dos caminos hacia la misma decisión:
  * el panel, para quien ya inició sesión;
  * el enlace del correo, para decidir sin entrar al sistema.

El enlace lleva un UUID aleatorio y **no aprueba por sí solo**: abre una
página que muestra la solicitud y exige confirmar. Un GET nunca cambia
estado — un antivirus corporativo que siga los enlaces de un correo no
puede aprobar vacaciones.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import notificaciones, qr
from ..audit import registrar
from ..config import get_settings
from ..db import obtener_todos, obtener_uno
from ..deps import usuario_actual
from ..errores import traducir

log = logging.getLogger("rrhh.aprobaciones")
router = APIRouter(tags=["Aprobaciones"])

SQL_SOLICITUD = """
    select r.id, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
           r.dias_solicitados, r.horas_solicitadas, r.descripcion, r.justificacion,
           r.es_adelanto, r.saldo_al_solicitar, r.fines_semana, r.created_at,
           r.jefe_id, r.jefe_token, r.rrhh_token, r.qr_hash, r.motivo_rechazo,
           r.user_id, u.nombre as empleado, u.cedula, u.email, u.departamento, u.cargo,
           u.dias_vacaciones as saldo_actual,
           pt.nombre as categoria, pt.requiere_adjunto,
           j.nombre as jefe_nombre,
           (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
           (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
    from public.requests r
    join public.users u on u.id = r.user_id
    left join public.users j on j.id = r.jefe_id
    left join public.permission_types pt on pt.id = r.permission_type_id
    where r.id = %s
"""


class Decision(BaseModel):
    accion: Literal["aprobar", "rechazar"]
    motivo: str | None = Field(None, max_length=300)


# --------------------------------------------------------------- utilidades
def _estado_esperado(rol: str) -> str:
    return "pendiente_jefe" if rol == "jefe" else "pendiente_rrhh"


def _publico(solicitud: dict) -> dict:
    """Lo que ve quien aprueba. Sin tokens ni identificadores internos."""
    return {
        "id": str(solicitud["id"]),
        "empleado": solicitud["empleado"],
        "cedula": solicitud["cedula"],
        "cargo": solicitud["cargo"],
        "departamento": solicitud["departamento"],
        "tipo": solicitud["tipo"],
        "categoria": solicitud["categoria"],
        "estado": solicitud["estado"],
        "fecha_inicio": solicitud["fecha_inicio"],
        "fecha_fin": solicitud["fecha_fin"],
        "hora_inicio": str(solicitud["hora_inicio"])[:5] if solicitud["hora_inicio"] else None,
        "hora_fin": str(solicitud["hora_fin"])[:5] if solicitud["hora_fin"] else None,
        "dias_solicitados": float(solicitud["dias_solicitados"]),
        "horas_solicitadas": float(solicitud["horas_solicitadas"]) if solicitud["horas_solicitadas"] else None,
        "descripcion": solicitud["descripcion"],
        "justificacion": solicitud["justificacion"],
        "es_adelanto": solicitud["es_adelanto"],
        "saldo_al_solicitar": float(solicitud["saldo_al_solicitar"]),
        "saldo_actual": float(solicitud["saldo_actual"]),
        "fines_semana": solicitud["fines_semana"],
        "adjuntos": solicitud["adjuntos"],
        "firmas": solicitud["firmas"],
        "jefe_nombre": solicitud["jefe_nombre"],
        "created_at": solicitud["created_at"],
        "motivo_rechazo": solicitud["motivo_rechazo"],
    }


async def _aplicar(solicitud: dict, rol: str, decision: Decision,
                   decidido_por: str | None, tareas: BackgroundTasks) -> dict:
    """Cambia el estado y encola los correos del paso siguiente."""
    if decision.accion == "rechazar" and not (decision.motivo or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Indique el motivo del rechazo: el empleado debe saber por qué."},
        )

    nuevo = ("pendiente_rrhh" if rol == "jefe" else "aprobado") if decision.accion == "aprobar" else "rechazado"
    columna_quien = "jefe_aprobado_por" if rol == "jefe" else "rrhh_aprobado_por"

    try:
        if decision.accion == "aprobar":
            actualizada = await obtener_uno(
                f"""
                update public.requests
                   set estado = %(estado)s, {columna_quien} = %(quien)s
                 where id = %(id)s and estado = %(esperado)s
                returning id, estado, qr_hash
                """,
                {"estado": nuevo, "quien": decidido_por, "id": solicitud["id"],
                 "esperado": _estado_esperado(rol)},
            )
        else:
            actualizada = await obtener_uno(
                """
                update public.requests
                   set estado = 'rechazado', rechazado_por = %(quien)s, motivo_rechazo = %(motivo)s
                 where id = %(id)s and estado = %(esperado)s
                returning id, estado, qr_hash
                """,
                {"quien": decidido_por, "motivo": decision.motivo.strip(),
                 "id": solicitud["id"], "esperado": _estado_esperado(rol)},
            )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    if actualizada is None:
        # Otra persona decidió entre que se cargó la página y se pulsó el botón
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "Esta solicitud ya fue resuelta por otra persona."},
        )

    completa = await obtener_uno(SQL_SOLICITUD, (solicitud["id"],))
    empleado = {"email": completa["email"], "nombre": completa["empleado"]}
    quien = (await obtener_uno("select nombre from public.users where id = %s", (decidido_por,)) or {}).get(
        "nombre", "Talento Humano"
    )

    if actualizada["estado"] == "pendiente_rrhh":
        personal_rrhh = await obtener_todos(
            "select email, nombre from public.users where rol in ('rrhh','admin') and activo"
        )
        tareas.add_task(notificaciones.avisar_a_rrhh, personal_rrhh, completa, quien)

    elif actualizada["estado"] == "aprobado":
        tareas.add_task(notificaciones.avisar_aprobacion, empleado, completa)

    elif actualizada["estado"] == "rechazado":
        tareas.add_task(notificaciones.avisar_rechazo, empleado, completa, quien, decision.motivo.strip())

    return {
        "id": str(actualizada["id"]),
        "estado": actualizada["estado"],
        "qr_emitido": actualizada["qr_hash"] is not None,
        "mensaje": {
            "pendiente_rrhh": "Aprobada. Pasó a Talento Humano.",
            "aprobado": "Aprobada. Se emitió el código QR y se avisó al empleado.",
            "rechazado": "Solicitud rechazada. Se avisó al empleado.",
        }[actualizada["estado"]],
    }


# ------------------------------------------------- camino 1: con sesión
@router.get("/aprobaciones/pendientes")
async def pendientes(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Lo que le toca decidir a quien consulta, según su rol."""
    if usuario["rol"] == "jefe":
        filtro, parametros = "r.jefe_id = %s and r.estado = 'pendiente_jefe'", (usuario["id"],)
    elif usuario["rol"] in ("rrhh", "admin"):
        filtro, parametros = "r.estado = 'pendiente_rrhh'", ()
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"mensaje": "Su perfil no aprueba solicitudes."},
        )

    filas = await obtener_todos(
        f"""
        select r.id, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
               r.dias_solicitados, r.horas_solicitadas, r.descripcion, r.justificacion,
               r.es_adelanto, r.saldo_al_solicitar, r.fines_semana, r.created_at, r.motivo_rechazo,
               u.nombre as empleado, u.cedula, u.departamento, u.cargo,
               u.dias_vacaciones as saldo_actual,
               pt.nombre as categoria, j.nombre as jefe_nombre,
               (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
               (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.users j on j.id = r.jefe_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        where {filtro}
        order by r.created_at
        """,
        parametros,
    )
    return [
        {**f, "id": str(f["id"]), "dias_solicitados": float(f["dias_solicitados"]),
         "saldo_al_solicitar": float(f["saldo_al_solicitar"]),
         "saldo_actual": float(f["saldo_actual"]),
         "hora_inicio": str(f["hora_inicio"])[:5] if f["hora_inicio"] else None,
         "hora_fin": str(f["hora_fin"])[:5] if f["hora_fin"] else None}
        for f in filas
    ]


@router.post("/aprobaciones/{solicitud_id}/decidir")
async def decidir(
    solicitud_id: uuid.UUID,
    decision: Decision,
    request: Request,
    tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    solicitud = await obtener_uno(SQL_SOLICITUD, (solicitud_id,))
    if solicitud is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Solicitud no encontrada."})

    # Nadie aprueba su propia solicitud, ni siquiera Talento Humano.
    # Va antes que el resto: es la razón más precisa para negar, y así el
    # mensaje explica lo que realmente ocurre.
    if str(solicitud["user_id"]) == str(usuario["id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"mensaje": "No puede aprobar su propia solicitud."},
        )

    # Quién puede decidir, y en qué estado
    if solicitud["estado"] == "pendiente_jefe":
        rol = "jefe"
        autorizado = str(solicitud["jefe_id"]) == str(usuario["id"]) or usuario["rol"] in ("rrhh", "admin")
    elif solicitud["estado"] == "pendiente_rrhh":
        rol = "rrhh"
        autorizado = usuario["rol"] in ("rrhh", "admin")
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": f"Esta solicitud ya está en estado «{solicitud['estado']}»."},
        )

    if not autorizado:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"mensaje": "No le corresponde decidir sobre esta solicitud."},
        )

    resultado = await _aplicar(solicitud, rol, decision, str(usuario["id"]), tareas)

    await registrar(request, f"solicitud_{decision.accion}da_por_{rol}",
                    user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="requests", entidad_id=str(solicitud_id),
                    detalle={"via": "panel", "motivo": decision.motivo})
    return resultado


# ------------------------------------------- camino 2: enlace del correo
async def _por_token(token: uuid.UUID, rol: str) -> dict:
    if rol not in ("jefe", "rrhh"):
        raise HTTPException(status_code=404, detail={"mensaje": "Enlace no válido."})

    columna = "jefe_token" if rol == "jefe" else "rrhh_token"
    solicitud = await obtener_uno(
        f"""
        select r.id from public.requests r
        where r.{columna} = %s
          and r.created_at > now() - make_interval(days => %s)
        """,
        (token, get_settings().aprobacion_link_dias),
    )
    if solicitud is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"mensaje": "Este enlace no es válido o ya venció. Ingrese al sistema para revisar la solicitud."},
        )
    return await obtener_uno(SQL_SOLICITUD, (solicitud["id"],))


@router.get("/aprobaciones/enlace/{token}")
async def ver_por_enlace(token: uuid.UUID, rol: str, request: Request) -> dict:
    """Muestra la solicitud. No cambia nada: decidir exige un POST."""
    solicitud = await _por_token(token, rol)

    await registrar(request, "aprobacion_enlace_abierto", entidad="requests",
                    entidad_id=str(solicitud["id"]), detalle={"rol": rol})

    return {
        "solicitud": _publico(solicitud),
        "rol": rol,
        "puede_decidir": solicitud["estado"] == _estado_esperado(rol),
        "aviso": None if solicitud["estado"] == _estado_esperado(rol)
                 else f"Esta solicitud ya está en estado «{solicitud['estado']}».",
    }


@router.post("/aprobaciones/enlace/{token}/decidir")
async def decidir_por_enlace(
    token: uuid.UUID, rol: str, decision: Decision, request: Request, tareas: BackgroundTasks
) -> dict:
    solicitud = await _por_token(token, rol)

    if solicitud["estado"] != _estado_esperado(rol):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": f"Esta solicitud ya está en estado «{solicitud['estado']}»."},
        )

    # Se registra a nombre de quien corresponde por el flujo, no de quien abrió el enlace
    decidido_por = str(solicitud["jefe_id"]) if rol == "jefe" else None
    if rol == "rrhh":
        encargado = await obtener_uno(
            "select id from public.users where rol in ('rrhh','admin') and activo order by rol limit 1"
        )
        decidido_por = str(encargado["id"]) if encargado else None

    resultado = await _aplicar(solicitud, rol, decision, decidido_por, tareas)

    await registrar(request, f"solicitud_{decision.accion}da_por_{rol}",
                    user_id=decidido_por, entidad="requests", entidad_id=str(solicitud["id"]),
                    detalle={"via": "enlace_correo", "motivo": decision.motivo})
    return resultado


# ------------------------------------------------------------------- QR
@router.get("/solicitudes/{solicitud_id}/qr.png")
async def qr_png(solicitud_id: uuid.UUID, usuario: Annotated[dict, Depends(usuario_actual)]) -> Response:
    """Imagen del QR. Solo el dueño de la solicitud, Talento Humano o garita."""
    solicitud = await obtener_uno(
        "select user_id, estado, qr_hash from public.requests where id = %s", (solicitud_id,)
    )
    if solicitud is None or solicitud["qr_hash"] is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Esta solicitud no tiene código QR."})

    if str(solicitud["user_id"]) != str(usuario["id"]) and usuario["rol"] not in ("rrhh", "admin", "guardia"):
        raise HTTPException(status_code=403, detail={"mensaje": "No puede ver este código."})

    if solicitud["estado"] != "aprobado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "El código solo es válido mientras la solicitud esté aprobada."},
        )

    return Response(
        content=qr.png(str(solicitud["qr_hash"])),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )
