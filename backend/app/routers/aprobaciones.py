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
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from .. import notificaciones, qr
from ..audit import registrar
from ..config import get_settings
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir

log = logging.getLogger("rrhh.aprobaciones")
router = APIRouter(tags=["Aprobaciones"])

SQL_SOLICITUD = """
    select r.id, r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
           r.dias_solicitados, r.horas_solicitadas, r.descripcion, r.justificacion,
           r.es_adelanto, r.saldo_al_solicitar, r.fines_semana, r.created_at,
           r.jefe_id, r.jefe_token, r.rrhh_token, r.qr_hash, r.motivo_rechazo,
           r.ruta_aprobacion, r.bloque_menor_justificado, r.reemplazo_id,
           rp.nombre as reemplazo,
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
    left join public.users rp on rp.id = r.reemplazo_id
    where r.id = %s
"""


class Decision(BaseModel):
    accion: Literal["aprobar", "rechazar"]
    motivo: str | None = Field(None, max_length=300)
    # Quién cubre el puesto. Lo decide el jefe al aprobar, no el solicitante:
    # es quien conoce la carga del equipo y quién puede asumirla. Se ignora
    # si lo envía cualquier otro rol.
    reemplazo_id: uuid.UUID | None = None


# --------------------------------------------------------------- utilidades
def _estado_esperado(rol: str) -> str:
    return "pendiente_jefe" if rol == "jefe" else "pendiente_rrhh"


def _siguiente_estado(rol: str, ruta: str) -> str:
    """A dónde pasa la solicitud cuando este rol aprueba.

    La ruta estándar es jefe → Talento Humano. Una vacación por debajo del
    bloque mínimo invierte el orden: quien autoriza apartarse de la política
    es Talento Humano, y recién entonces el jefe evalúa la cobertura del
    puesto. En ambas rutas aprueba el segundo y queda aprobada.
    """
    if ruta == "rrhh_primero":
        return "pendiente_jefe" if rol != "jefe" else "aprobado"
    return "pendiente_rrhh" if rol == "jefe" else "aprobado"


def _publico(solicitud: dict) -> dict:
    """Lo que ve quien aprueba. Sin tokens ni identificadores internos."""
    return {
        "id": str(solicitud["id"]),
        "folio": solicitud["folio"],
        "empleado": solicitud["empleado"],
        "reemplazo": solicitud["reemplazo"],
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

    if decision.reemplazo_id and str(decision.reemplazo_id) == str(solicitud["user_id"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Nadie puede cubrirse a sí mismo."},
        )

    ruta = solicitud.get("ruta_aprobacion") or "estandar"
    nuevo = _siguiente_estado(rol, ruta) if decision.accion == "aprobar" else "rechazado"
    columna_quien = "jefe_aprobado_por" if rol == "jefe" else "rrhh_aprobado_por"

    try:
        if decision.accion == "aprobar":
            # El reemplazo solo lo fija el jefe; si no manda uno, se conserva
            # el que ya hubiera (una segunda vuelta no debe borrarlo).
            actualizada = await obtener_uno(
                f"""
                update public.requests
                   set estado = %(estado)s, {columna_quien} = %(quien)s,
                       reemplazo_id = case when %(fija_reemplazo)s
                                           then %(reemplazo)s else reemplazo_id end
                 where id = %(id)s and estado = %(esperado)s
                returning id, estado, qr_hash
                """,
                {"estado": nuevo, "quien": decidido_por, "id": solicitud["id"],
                 "esperado": _estado_esperado(rol),
                 "fija_reemplazo": rol == "jefe" and decision.reemplazo_id is not None,
                 "reemplazo": decision.reemplazo_id},
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

    elif actualizada["estado"] == "pendiente_jefe":
        # Solo ocurre en la ruta invertida: Talento Humano ya autorizó la
        # excepción y ahora el jefe decide si puede cubrir el puesto.
        jefe = await obtener_uno(
            "select email, nombre from public.users where id = %s and activo",
            (completa["jefe_id"],),
        )
        if jefe:
            tareas.add_task(notificaciones.avisar_al_jefe, jefe, completa)

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
            "pendiente_jefe": "Excepción autorizada. Pasó al jefe inmediato para que confirme la cobertura.",
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
        # Talento Humano y administración también hacen de jefe de su propio
        # equipo; si no, una excepción devuelta por la ruta invertida a un
        # jefe con rol rrhh se quedaba sin nadie que la viera.
        filtro = "(r.estado = 'pendiente_rrhh' or (r.jefe_id = %s and r.estado = 'pendiente_jefe'))"
        parametros = (usuario["id"],)
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"mensaje": "Su perfil no aprueba solicitudes."},
        )

    filas = await obtener_todos(
        f"""
        select r.id, r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
               r.dias_solicitados, r.horas_solicitadas, r.descripcion, r.justificacion,
               r.es_adelanto, r.saldo_al_solicitar, r.fines_semana, r.created_at, r.motivo_rechazo,
               r.ruta_aprobacion, r.bloque_menor_justificado, r.reemplazo_id, r.user_id,
               u.nombre as empleado, u.cedula, u.departamento, u.cargo, rp.nombre as reemplazo,
               u.dias_vacaciones as saldo_actual,
               pt.nombre as categoria, j.nombre as jefe_nombre,
               (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
               (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.users j on j.id = r.jefe_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        left join public.users rp on rp.id = r.reemplazo_id
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


# ------------------------------------------------------------- anulaciones
@router.get("/aprobaciones/anulaciones")
async def anulaciones_pendientes(
    usuario: Annotated[dict, Depends(usuario_actual)]
) -> list[dict]:
    """Pedidos de anulación de solicitudes ya aprobadas."""
    if usuario["rol"] not in ("rrhh", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"mensaje": "Solo Talento Humano resuelve anulaciones."})

    filas = await obtener_todos(
        """
        select r.id, r.folio, r.tipo::text, pt.nombre as categoria,
               r.fecha_inicio, r.fecha_fin, r.dias_solicitados, r.descripcion,
               r.anulacion_motivo, r.anulacion_solicitada_en, r.qr_usado_en,
               u.nombre as empleado, u.cedula, u.departamento
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        where r.estado = 'pendiente_anulacion'
        order by r.anulacion_solicitada_en
        """
    )
    return [{**f, "id": str(f["id"]), "dias_solicitados": float(f["dias_solicitados"])}
            for f in filas]


@router.post("/aprobaciones/{solicitud_id}/anulacion")
async def resolver_anulacion(
    solicitud_id: uuid.UUID,
    decision: Decision,
    request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Autorizar la anulación devuelve los días y deja el QR sin efecto."""
    if usuario["rol"] not in ("rrhh", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"mensaje": "Solo Talento Humano resuelve anulaciones."})

    if decision.accion == "rechazar" and not (decision.motivo or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Indique por qué no se autoriza la anulación."},
        )

    nuevo = "cancelado" if decision.accion == "aprobar" else "aprobado"
    try:
        fila = await obtener_uno(
            """
            update public.requests
               set estado = %(estado)s,
                   anulacion_resuelta_por = %(quien)s,
                   anulacion_rechazada_motivo = %(motivo)s
             where id = %(id)s and estado = 'pendiente_anulacion'
            returning id, folio, estado::text, dias_solicitados
            """,
            {"estado": nuevo, "quien": usuario["id"], "id": solicitud_id,
             "motivo": (decision.motivo or "").strip() or None},
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    if fila is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"mensaje": "Esa solicitud ya no tiene una anulación pendiente."})

    await registrar(request, f"anulacion_{decision.accion}da", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="requests", entidad_id=str(solicitud_id),
                    detalle={"folio": fila["folio"], "motivo": decision.motivo})

    return {
        "id": str(fila["id"]), "estado": fila["estado"],
        "mensaje": (f"Anulación autorizada: se devolvieron {float(fila['dias_solicitados']):g} día(s) "
                    "y el código QR quedó sin efecto.")
                   if nuevo == "cancelado"
                   else "Anulación no autorizada: la solicitud sigue vigente.",
    }


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


# --------------------------------------------- quién puede cubrir el puesto
@router.get("/aprobaciones/{solicitud_id}/candidatos")
async def candidatos_reemplazo(
    solicitud_id: uuid.UUID, usuario: Annotated[dict, Depends(usuario_actual)]
) -> list[dict]:
    """Compañeros que podrían cubrir la ausencia, para que el jefe elija.

    Se calcula sobre el equipo del solicitante, no sobre el de quien consulta:
    Talento Humano puede estar revisando la solicitud de otra área.
    """
    solicitud = await obtener_uno(
        """select r.user_id, r.jefe_id, r.fecha_inicio, r.fecha_fin, u.departamento
             from public.requests r join public.users u on u.id = r.user_id
            where r.id = %s""",
        (solicitud_id,),
    )
    if solicitud is None:
        raise HTTPException(status_code=404, detail={"mensaje": "La solicitud no existe."})

    if str(solicitud["jefe_id"]) != str(usuario["id"]) and usuario["rol"] not in ("rrhh", "admin"):
        raise HTTPException(status_code=403, detail={"mensaje": "No le corresponde esta solicitud."})

    # Se marca quién estará ausente en esas mismas fechas: proponer a alguien
    # que también está de vacaciones es el error más fácil de cometer.
    return await obtener_todos(
        """
        select u.id, u.nombre, u.cargo,
               exists (
                 select 1 from public.requests o
                  where o.user_id = u.id
                    and o.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
                    and o.fecha_inicio <= %(fin)s and o.fecha_fin >= %(inicio)s
               ) as tambien_ausente
        from public.users u
        where u.activo and u.id <> %(solicitante)s
          and (u.jefe_id = %(jefe)s or u.departamento = %(depto)s)
        order by tambien_ausente, u.nombre
        limit 100
        """,
        {"solicitante": solicitud["user_id"], "jefe": solicitud["jefe_id"],
         "depto": solicitud["departamento"], "inicio": solicitud["fecha_inicio"],
         "fin": solicitud["fecha_fin"]},
    )


# ------------------------------------- ajuste de una ausencia ya autorizada
class AjusteAusencia(BaseModel):
    """Extensión o corrección de una ausencia aprobada.

    El caso que la motiva: un permiso de dos horas por cita médica del que
    sale un reposo de tres días. Sin esto, garita seguía esperando a la
    persona y el jefe la daba por presente.
    """
    fecha_inicio: date
    fecha_fin: date
    motivo: str = Field(..., min_length=15, max_length=600,
                        description="Qué ocurrió, en palabras de quien ajusta")
    resolucion: str = Field(..., min_length=15, max_length=600,
                            description="Qué se resolvió y con qué respaldo")


@router.post("/aprobaciones/{solicitud_id}/ajustar")
async def ajustar_ausencia(
    solicitud_id: uuid.UUID, datos: AjusteAusencia, request: Request,
    tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))],
) -> dict:
    """Talento Humano extiende o corrige una ausencia ya aprobada.

    La base mueve fechas, días, saldo y constancia en una sola transacción
    (`ajustar_ausencia`): un reposo que se alarga no puede dejar el saldo a
    medias. El ajuste nunca borra el original: queda en `request_adjustments`
    con autor, momento y la explicación de por qué se hizo.
    """
    try:
        # `from`, no `select (fn(...)).*`: esa forma expande el registro
        # llamando a la función una vez por columna —46 veces, y 46 ajustes
        # registrados—. En `from` se evalúa una sola vez.
        fila = await obtener_uno(
            """select * from public.ajustar_ausencia(%s, %s, %s, %s, %s, %s)""",
            (solicitud_id, datos.fecha_inicio, datos.fecha_fin,
             datos.motivo, datos.resolucion, usuario["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    completa = await obtener_uno(SQL_SOLICITUD, (solicitud_id,))
    await registrar(
        request, "ausencia_ajustada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
        entidad="requests", entidad_id=str(solicitud_id),
        detalle={"folio": completa["folio"], "hasta": str(datos.fecha_fin),
                 "dias": float(fila["dias_solicitados"])},
    )

    # El interesado y su jefe deben enterarse: uno para saber hasta cuándo
    # está cubierto, el otro para no contar con alguien que no vendrá.
    destinos = [{"email": completa["email"], "nombre": completa["empleado"]}]
    jefe = await obtener_uno(
        "select email, nombre from public.users where id = %s and activo",
        (completa["jefe_id"],),
    )
    if jefe:
        destinos.append(jefe)
    tareas.add_task(notificaciones.avisar_ajuste, destinos, completa,
                    usuario["nombre"], datos.motivo, datos.resolucion)

    return {
        "id": str(solicitud_id),
        "folio": completa["folio"],
        "fecha_inicio": str(fila["fecha_inicio"]),
        "fecha_fin": str(fila["fecha_fin"]),
        "dias_solicitados": float(fila["dias_solicitados"]),
        "mensaje": "Ausencia ajustada. Se avisó al colaborador y a su jefe, "
                   "y garita ya reconoce las nuevas fechas.",
    }


@router.get("/solicitudes/{solicitud_id}/ajustes")
async def ajustes_de(
    solicitud_id: uuid.UUID, usuario: Annotated[dict, Depends(usuario_actual)]
) -> list[dict]:
    """Historial de ajustes. Lo ve el interesado, su jefe y Talento Humano."""
    solicitud = await obtener_uno(
        "select user_id, jefe_id from public.requests where id = %s", (solicitud_id,)
    )
    if solicitud is None:
        raise HTTPException(status_code=404, detail={"mensaje": "La solicitud no existe."})

    propio = str(solicitud["user_id"]) == str(usuario["id"])
    es_jefe = str(solicitud["jefe_id"]) == str(usuario["id"])
    if not (propio or es_jefe or usuario["rol"] in ("rrhh", "admin")):
        raise HTTPException(status_code=403, detail={"mensaje": "No puede ver este historial."})

    return await obtener_todos(
        """
        select a.id, a.fecha_inicio_ant, a.fecha_fin_ant,
               a.fecha_inicio_nueva, a.fecha_fin_nueva,
               a.dias_ant, a.dias_nuevos, a.motivo, a.resolucion,
               a.created_at, u.nombre as ajustado_por
        from public.request_adjustments a
        join public.users u on u.id = a.ajustado_por
        where a.request_id = %s
        order by a.created_at desc
        """,
        (solicitud_id,),
    )
