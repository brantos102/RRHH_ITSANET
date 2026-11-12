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
from ..db import booleanos, ejecutar, obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir
from ..reglas import papeles as reglas_papeles
from ..reglas import personal
from ..reglas import solicitudes as reglas_solicitudes

log = logging.getLogger("rrhh.aprobaciones")
router = APIRouter(tags=["Aprobaciones"])

SQL_SOLICITUD = """
    select r.id, r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
           r.dias_solicitados, r.horas_solicitadas, r.descripcion, r.justificacion,
           r.es_adelanto, r.saldo_al_solicitar, r.fines_semana, r.created_at,
           r.jefe_id, r.jefe_token, r.rrhh_token, r.qr_hash, r.motivo_rechazo,
           r.ruta_aprobacion, r.bloque_menor_justificado, r.reemplazo_id, r.region,
           rp.nombre as reemplazo, r.reemplazo_asignado_por, r.reemplazo_confirmado_en,
           r.user_id, u.nombre as empleado, u.cedula, u.email, u.departamento, u.cargo,
           u.dias_vacaciones as saldo_actual,
           pt.nombre as categoria, pt.requiere_adjunto,
           j.nombre as jefe_nombre,
           (select count(*) from request_attachments a where a.request_id = r.id) as adjuntos
    from requests r
    join users u on u.id = r.user_id
    left join users j on j.id = r.jefe_id
    left join permission_types pt on pt.id = r.permission_type_id
    left join users rp on rp.id = r.reemplazo_id
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
        "reemplazo_asignado_por": solicitud["reemplazo_asignado_por"],
        "reemplazo_confirmado": solicitud["reemplazo_confirmado_en"] is not None,
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
        "jefe_nombre": solicitud["jefe_nombre"],
        "created_at": solicitud["created_at"],
        "motivo_rechazo": solicitud["motivo_rechazo"],
    }


def _reemplazo_al_aprobar(solicitud: dict, decision: Decision,
                          decidido_por: str | None) -> tuple[str, dict, bool]:
    """Qué hacer con el reemplazo al aprobar: (SQL extra, parámetros, avisar al jefe).

    El reemplazo lo elige el jefe inmediato: sabe si esa persona ya tiene
    otras tareas. Talento Humano lo confirma para el registro, no lo cambia.
    Si nadie eligió, Talento Humano puede asignar a alguien, y entonces se le
    pide al jefe que lo confirme o lo cambie.
    """
    if decision.accion != "aprobar":
        return "", {}, False
    actual = solicitud.get("reemplazo_id")
    asignado = solicitud.get("reemplazo_asignado_por")
    nuevo = decision.reemplazo_id
    tiene_jefe = solicitud.get("jefe_id") is not None
    es_el_jefe = tiene_jefe and decidido_por is not None and str(solicitud["jefe_id"]) == str(decidido_por)

    fijar = """, reemplazo_id = %(r_id)s, reemplazo_asignado_por = %(r_por)s,
               reemplazo_confirmado_en = IF(%(r_confirmado)s, NOW(6), NULL),
               reemplazo_confirmado_por = IF(%(r_confirmado)s, %(r_quien)s, NULL)"""
    confirmar = ", reemplazo_confirmado_en = NOW(6), reemplazo_confirmado_por = %(r_quien)s"

    if es_el_jefe:
        if nuevo is not None:
            return fijar, {"r_id": nuevo, "r_por": "jefe", "r_confirmado": True,
                           "r_quien": decidido_por}, False
        if actual is not None and asignado == "rrhh" and solicitud.get("reemplazo_confirmado_en") is None:
            # Aprobar viendo el reemplazo que puso Talento Humano es confirmarlo.
            return confirmar, {"r_quien": decidido_por}, False
        return "", {}, False

    # Talento Humano (o administración), o quien decide por un jefe que no hay.
    if nuevo is None or (actual is not None and str(actual) == str(nuevo)):
        return "", {}, False
    if actual is not None and asignado == "jefe":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": f"El reemplazo lo eligió el jefe inmediato ({solicitud.get('reemplazo')}). "
                               "Talento Humano lo confirma para el registro, no lo cambia: si hace "
                               "falta otra persona, coordínelo con el jefe."},
        )
    # Sin jefe no hay a quién pedir confirmación: queda confirmado por quien decide.
    return fijar, {"r_id": nuevo, "r_por": "rrhh", "r_confirmado": not tiene_jefe,
                   "r_quien": decidido_por}, tiene_jefe


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
    reemplazo_sql, reemplazo_params, avisar_al_jefe = _reemplazo_al_aprobar(solicitud, decision, decidido_por)

    try:
        if decision.accion == "aprobar":
            cambiadas = await ejecutar(
                f"""
                update requests
                   set estado = %(estado)s, {columna_quien} = %(quien)s {reemplazo_sql}
                 where id = %(id)s and estado = %(esperado)s
                """,
                {"estado": nuevo, "quien": decidido_por, "id": solicitud["id"],
                 "esperado": _estado_esperado(rol), **reemplazo_params},
            )
        else:
            cambiadas = await ejecutar(
                """
                update requests
                   set estado = 'rechazado', rechazado_por = %(quien)s, motivo_rechazo = %(motivo)s
                 where id = %(id)s and estado = %(esperado)s
                """,
                {"quien": decidido_por, "motivo": decision.motivo.strip(),
                 "id": solicitud["id"], "esperado": _estado_esperado(rol)},
            )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    # Sin RETURNING en MySQL: ninguna fila tocada = el estado ya no era el
    # esperado. Si se tocó, se lee cómo quedó (el disparador emite el QR).
    actualizada = None
    if cambiadas:
        actualizada = await obtener_uno("SELECT id, estado, qr_hash FROM requests WHERE id = %s",
                                        (solicitud["id"],))
    if actualizada is None:
        # Otra persona decidió entre que se cargó la página y se pulsó el botón
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "Esta solicitud ya fue resuelta por otra persona."},
        )

    completa = await obtener_uno(SQL_SOLICITUD, (solicitud["id"],))
    empleado = {"email": completa["email"], "nombre": completa["empleado"]}
    quien = (await obtener_uno("select nombre from users where id = %s", (decidido_por,)) or {}).get(
        "nombre", "Talento Humano"
    )

    if avisar_al_jefe:
        jefe = await obtener_uno("select email, nombre from users where id = %s and activo and email is not null",
                                 (completa["jefe_id"],))
        if jefe:
            tareas.add_task(notificaciones.avisar_reemplazo_por_confirmar, jefe, completa, quien)

    if actualizada["estado"] == "pendiente_rrhh":
        # Al grupo de la región, no a un buzón concreto: si alguien está de
        # vacaciones, la solicitud igual se resuelve.
        personal_rrhh = [{"email": d["email"], "nombre": d["nombre"]}
                         for d in await personal.rrhh_de_region(completa.get("region") or "sierra")]
        adjuntos = await _documentos_para_rrhh(completa) if completa["tipo"] == "vacacion" else []
        tareas.add_task(notificaciones.avisar_a_rrhh, personal_rrhh, completa, quien, adjuntos)

    elif actualizada["estado"] == "pendiente_jefe":
        # Solo ocurre en la ruta invertida: Talento Humano ya autorizó la
        # excepción y ahora el jefe decide si puede cubrir el puesto.
        jefe = await obtener_uno(
            "select email, nombre from users where id = %s and activo",
            (completa["jefe_id"],),
        )
        if jefe:
            tareas.add_task(notificaciones.avisar_al_jefe, jefe, completa)

    elif actualizada["estado"] == "aprobado":
        sede = None
        if completa["tipo"] == "vacacion":
            sede = await _avisar_que_firme(completa)
        tareas.add_task(notificaciones.avisar_aprobacion, empleado, completa, sede)

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


async def _documentos_para_rrhh(solicitud: dict) -> list[tuple[str, bytes, str]]:
    """La solicitud y la constancia de goce, en PDF, para el correo a Talento
    Humano cuando el jefe ya aprobó: las imprime, las firma, y el colaborador
    solo tiene que acercarse a firmar.

    Un fallo aquí no detiene la aprobación: el aviso sale igual, sin adjuntos,
    y los documentos siguen disponibles en el sistema.
    """
    from ..documentos import armar, nombre_archivo
    try:
        sol = await reglas_papeles.informe_solicitud_asegurar(str(solicitud["id"]))
        traz = await reglas_papeles.informe_trazabilidad_asegurar(str(solicitud["user_id"]))
        firmante = await reglas_papeles.firmante_por_defecto(solicitud["user_id"])
        return [(nombre_archivo(i), armar(i, firmante), "application/pdf") for i in (sol, traz)]
    except Exception:  # noqa: BLE001
        log.exception("No se pudieron preparar los documentos de la solicitud %s",
                      solicitud.get("folio"))
        return []


async def _avisar_que_firme(solicitud: dict) -> str | None:
    """Aprobada por Talento Humano: el colaborador tiene que acercarse a firmar
    para concluir. Queda como aviso dentro del sistema; el correo lo dice también."""
    fila = await obtener_uno("SELECT sede FROM regiones WHERE codigo = %s",
                             (solicitud.get("region") or "sierra",))
    sede = (fila or {}).get("sede")
    try:
        await reglas_papeles.informe_solicitud_asegurar(str(solicitud["id"]))
        await ejecutar(
            """INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje,
                                          entidad, entidad_id, clave_dedupe, accion_url)
               VALUES (%s, 'documento_faltante', 'advertencia', %s, %s, 'requests', %s, %s,
                       'dashboard.html#papeles')
               ON DUPLICATE KEY UPDATE clave_dedupe = clave_dedupe""",
            (str(solicitud["user_id"]), "Acérquese a firmar sus vacaciones",
             f"Su solicitud N.º {solicitud['folio']} fue aprobada. Acérquese a Talento Humano"
             + (f" de {sede}" if sede else "") + " a firmar la solicitud y la constancia para "
             "concluir el proceso.", str(solicitud["id"]), f"firmar-{solicitud['id']}"))
    except Exception:  # noqa: BLE001
        log.exception("No se pudo dejar el aviso de firma de la solicitud %s", solicitud.get("folio"))
    return sede


# ------------------------------------------------- camino 1: con sesión
@router.get("/aprobaciones/pendientes")
async def pendientes(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Lo que le toca decidir a quien consulta, según su rol."""
    if usuario["rol"] == "jefe":
        filtro, parametros = "r.jefe_id = %s and r.estado = 'pendiente_jefe'", (usuario["id"],)
    elif usuario["rol"] == "rrhh":
        # Talento Humano resuelve lo de SU región: quien atiende a la gente de
        # Quito tiene sus papeles a mano y la conoce. Cualquier miembro de esa
        # región puede decidir, así que nadie espera a una persona concreta.
        # Y también hace de jefe de su propio equipo: sin esto, una excepción
        # devuelta por la ruta invertida a un jefe con rol rrhh se quedaba sin
        # nadie que la viera.
        #
        # Y LO HUÉRFANO. Quien no tiene jefe asignado —quince de las 351
        # personas de la planilla— generaba una solicitud en `pendiente_jefe`
        # con `jefe_id` nulo. La bandeja del jefe filtra por `jefe_id = <el
        # mío>` y nulo no es nadie; esta filtraba por `pendiente_rrhh`, que es
        # un paso después. La solicitud existía, el colaborador la veía
        # «pendiente» y no había una sola pantalla desde la que decidirla.
        # Decidirla sí se podía: lo que faltaba era poder encontrarla.
        filtro = """(
            (r.estado = 'pendiente_rrhh' and coalesce(r.region, 'sierra') = %s)
            or (r.estado = 'pendiente_jefe' and r.jefe_id is null
                and coalesce(r.region, 'sierra') = %s)
            or (r.jefe_id = %s and r.estado = 'pendiente_jefe')
        )"""
        region = usuario.get("region") or "sierra"
        parametros = (region, region, usuario["id"])
    elif usuario["rol"] == "admin":
        # Administración ve todas las regiones: es quien cubre los huecos, y
        # el hueco de quien no tiene jefe es justo uno de ellos.
        filtro = """(
            r.estado = 'pendiente_rrhh'
            or (r.estado = 'pendiente_jefe' and r.jefe_id is null)
            or (r.jefe_id = %s and r.estado = 'pendiente_jefe')
        )"""
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
               r.ruta_aprobacion, r.bloque_menor_justificado, r.reemplazo_id, r.user_id, r.jefe_id,
               r.reemplazo_asignado_por, r.reemplazo_confirmado_en is not null as reemplazo_confirmado,
               r.region,
               (select q.nombre from atenciones a join users q on q.id = a.user_id
                 where a.tipo = 'solicitud' and a.entidad_id = r.id and a.user_id <> %s
                   and a.tomado_en > NOW(6) - INTERVAL 4 HOUR) as en_revision_por,
               u.nombre as empleado, u.cedula, u.departamento, u.cargo, rp.nombre as reemplazo,
               u.dias_vacaciones as saldo_actual,
               pt.nombre as categoria, j.nombre as jefe_nombre,
               -- Decidir por un jefe que NO EXISTE no es lo mismo que decidir
               -- por uno que no contesta, y quien resuelve tiene que poder
               -- distinguirlo antes de firmar.
               r.jefe_id is null as sin_jefe,
               (select count(*) from request_attachments a where a.request_id = r.id) as adjuntos
        from requests r
        join users u on u.id = r.user_id
        left join users j on j.id = r.jefe_id
        left join permission_types pt on pt.id = r.permission_type_id
        left join users rp on rp.id = r.reemplazo_id
        where {filtro}
        order by r.created_at
        """,
        (usuario["id"], *parametros),
    )
    return [
        {**f, "id": str(f["id"]), "dias_solicitados": float(f["dias_solicitados"]),
         "saldo_al_solicitar": float(f["saldo_al_solicitar"]),
         "saldo_actual": float(f["saldo_actual"]),
         "hora_inicio": str(f["hora_inicio"])[:5] if f["hora_inicio"] else None,
         "hora_fin": str(f["hora_fin"])[:5] if f["hora_fin"] else None}
        for f in booleanos(filas, "sin_jefe", "reemplazo_confirmado")
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
        select r.id from requests r
        where r.{columna} = %s
          and r.created_at > now(6) - interval %s day
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
            "select id from users where rol in ('rrhh','admin') and activo order by rol limit 1"
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
        select r.id, r.folio, r.tipo, pt.nombre as categoria,
               r.fecha_inicio, r.fecha_fin, r.dias_solicitados, r.descripcion,
               r.anulacion_motivo, r.anulacion_solicitada_en, r.qr_usado_en,
               u.nombre as empleado, u.cedula, u.departamento
        from requests r
        join users u on u.id = r.user_id
        left join permission_types pt on pt.id = r.permission_type_id
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
        cambiadas = await ejecutar(
            """
            update requests
               set estado = %(estado)s,
                   anulacion_resuelta_por = %(quien)s,
                   anulacion_rechazada_motivo = %(motivo)s
             where id = %(id)s and estado = 'pendiente_anulacion'
            """,
            {"estado": nuevo, "quien": usuario["id"], "id": solicitud_id,
             "motivo": (decision.motivo or "").strip() or None},
        )
        fila = (await obtener_uno("SELECT id, folio, estado, dias_solicitados FROM requests WHERE id = %s",
                                  (solicitud_id,)) if cambiadas else None)
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
        "select user_id, estado, qr_hash from requests where id = %s", (solicitud_id,)
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


# --------------------------------------- el jefe confirma el reemplazo de TH
class ConfirmacionReemplazo(BaseModel):
    accion: Literal["confirmar", "cambiar"]
    # Con «cambiar»: a quién elige el jefe. Vacío = nadie cubre el puesto.
    reemplazo_id: uuid.UUID | None = None


@router.get("/aprobaciones/reemplazos-por-confirmar")
async def reemplazos_por_confirmar(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Reemplazos que Talento Humano asignó a gente de este jefe y que él aún no confirmó."""
    filas = await obtener_todos(
        """select r.id, r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin,
                  u.nombre as empleado, rp.nombre as reemplazo, q.nombre as asignado_por
             from requests r
             join users u on u.id = r.user_id
             left join users rp on rp.id = r.reemplazo_id
             left join users q on q.id = r.rrhh_aprobado_por
            where r.jefe_id = %s and r.reemplazo_asignado_por = 'rrhh'
              and r.reemplazo_confirmado_en is null
              and r.estado not in ('rechazado', 'cancelado')
            order by r.fecha_inicio""",
        (usuario["id"],))
    return [{**f, "id": str(f["id"])} for f in filas]


@router.post("/aprobaciones/{solicitud_id}/reemplazo")
async def confirmar_reemplazo(
    solicitud_id: uuid.UUID, datos: ConfirmacionReemplazo, request: Request,
    tareas: BackgroundTasks, usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """El jefe confirma el reemplazo que asignó Talento Humano, o elige otro."""
    solicitud = await obtener_uno(SQL_SOLICITUD, (str(solicitud_id),))
    if solicitud is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Solicitud no encontrada."})
    if str(solicitud["jefe_id"]) != str(usuario["id"]) and usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail={
            "mensaje": "Solo el jefe inmediato confirma el reemplazo de su equipo."})
    if (solicitud["reemplazo_asignado_por"] != "rrhh" or solicitud["reemplazo_confirmado_en"] is not None
            or solicitud["estado"] in ("rechazado", "cancelado")):
        raise HTTPException(status_code=409, detail={
            "mensaje": "Este reemplazo no está pendiente de confirmación."})

    if datos.accion == "confirmar":
        await ejecutar("""update requests set reemplazo_confirmado_en = NOW(6), reemplazo_confirmado_por = %s
                           where id = %s""", (usuario["id"], str(solicitud_id)))
        mensaje = f"Reemplazo confirmado: {solicitud['reemplazo']} cubre a {solicitud['empleado']}."
    else:
        if datos.reemplazo_id is not None:
            if str(datos.reemplazo_id) == str(solicitud["user_id"]):
                raise HTTPException(status_code=422, detail={"mensaje": "Nadie puede cubrirse a sí mismo."})
            if await obtener_uno("select 1 as x from users where id = %s and activo",
                                 (str(datos.reemplazo_id),)) is None:
                raise HTTPException(status_code=422, detail={"mensaje": "Esa persona no está activa."})
        await ejecutar(
            """update requests set reemplazo_id = %s, reemplazo_asignado_por = 'jefe',
                      reemplazo_confirmado_en = NOW(6), reemplazo_confirmado_por = %s
                where id = %s""", (datos.reemplazo_id, usuario["id"], str(solicitud_id)))
        completa = await obtener_uno(SQL_SOLICITUD, (str(solicitud_id),))
        destinatarios = [{"email": d["email"]} for d in
                         await personal.rrhh_de_region(completa.get("region") or "sierra")]
        tareas.add_task(notificaciones.avisar_reemplazo_cambiado, destinatarios, completa,
                        usuario["nombre"], solicitud["reemplazo"])
        mensaje = (f"Reemplazo cambiado: ahora cubre {completa['reemplazo']}." if completa["reemplazo"]
                   else "Quedó sin reemplazo.") + " Se avisó a Talento Humano."

    await registrar(request, f"reemplazo_{datos.accion}", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="requests", entidad_id=str(solicitud_id),
                    detalle={"reemplazo_id": str(datos.reemplazo_id) if datos.reemplazo_id else None})
    return {"mensaje": mensaje}


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
             from requests r join users u on u.id = r.user_id
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
                 select 1 from requests o
                  where o.user_id = u.id
                    and o.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
                    and o.fecha_inicio <= %(fin)s and o.fecha_fin >= %(inicio)s
               ) as tambien_ausente
        from users u
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

    Fechas, días, saldo y constancia se mueven en una sola transacción
    (reglas.solicitudes.ajustar_ausencia): un reposo que se alarga no puede
    dejar el saldo a medias. El ajuste nunca borra el original: queda en `request_adjustments`
    con autor, momento y la explicación de por qué se hizo.
    """
    try:
        fila = await reglas_solicitudes.ajustar_ausencia(
            solicitud_id, datos.fecha_inicio, datos.fecha_fin,
            datos.motivo, datos.resolucion, usuario["id"])
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
        "select email, nombre from users where id = %s and activo",
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
        "select user_id, jefe_id from requests where id = %s", (solicitud_id,)
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
        from request_adjustments a
        join users u on u.id = a.ajustado_por
        where a.request_id = %s
        order by a.created_at desc
        """,
        (solicitud_id,),
    )
