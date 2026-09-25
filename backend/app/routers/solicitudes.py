"""Solicitudes del empleado: catálogo, previsualización, envío y consulta."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, time, timedelta
from typing import Annotated, Literal

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException, Request,
                     UploadFile, status)
from pydantic import BaseModel, Field, field_validator
from psycopg import errors as pg

from .. import notificaciones
from ..audit import registrar
from ..db import conexion, obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir
from ..storage import subir_adjunto

log = logging.getLogger("rrhh.solicitudes")
router = APIRouter(tags=["Solicitudes"])

MIMES_PERMITIDOS = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
TAMANO_MAXIMO = 10 * 1024 * 1024


# --------------------------------------------------------------- contratos
class AdjuntoEntrada(BaseModel):
    storage_path: str
    nombre_archivo: str
    mime_type: str
    tamano_bytes: int
    hash_sha256: str | None = None


class Previsualizacion(BaseModel):
    tipo: Literal["permiso", "vacacion"]
    fecha_inicio: date
    fecha_fin: date
    permission_type_id: int | None = None


class NuevaSolicitud(BaseModel):
    # El cliente genera el id para poder subir los adjuntos antes de enviar
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tipo: Literal["permiso", "vacacion"]
    permission_type_id: int | None = None
    fecha_inicio: date
    fecha_fin: date
    hora_inicio: time | None = None
    hora_fin: time | None = None
    descripcion: str = Field(..., min_length=5, max_length=200)
    justificacion: str | None = None
    # Vacaciones por debajo del bloque mínimo. Marcarlo no basta: la base
    # exige justificación y respaldo, y desvía la solicitud a Talento Humano.
    # Quién cubre la ausencia NO se pide aquí: lo asigna el jefe al aprobar,
    # que es quien conoce la carga del equipo.
    bloque_menor_justificado: bool = False
    adjuntos: list[AdjuntoEntrada] = []
    firmar: bool = True

    @field_validator("descripcion", "justificacion")
    @classmethod
    def limpiar(cls, v: str | None) -> str | None:
        return v.strip() if v else v


# --------------------------------------------------------------- catálogo
@router.get("/catalogos/tipos-permiso")
async def tipos_permiso(_: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Tipos de permiso vigentes, con lo que exige cada uno y su base legal.

    Se mantiene la lista plana para lo que ya la consume (administración,
    informes). El formulario del colaborador usa `/catalogos/permisos`, que
    la entrega agrupada por pilar.
    """
    return await obtener_todos(
        """
        select pt.id, pt.codigo, pt.nombre, pt.descripcion,
               pt.requiere_adjunto, pt.requiere_justificacion, pt.requiere_firma,
               pt.remunerado, pt.descuenta_vacaciones, pt.max_dias, pt.max_horas,
               pt.guia_ejemplo, pt.guia_adjuntos,
               c.codigo as categoria_codigo, c.nombre as categoria_nombre,
               l.norma, l.articulo, l.titulo as articulo_titulo, l.texto as articulo_texto
        from public.permission_types pt
        left join public.permission_categories c on c.id = pt.category_id
        left join public.legal_references l on l.codigo = pt.legal_ref
        where pt.activo
        order by pt.orden
        """
    )


@router.get("/catalogos/permisos")
async def catalogo_permisos(_: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """Los tres pilares con sus subtipos y la guía de redacción de cada uno.

    Elegir entre tres preguntas —emergencia del hogar, salud, asunto propio—
    y luego afinar es mucho más rápido que leer veinte opciones planas. Cada
    subtipo viaja con su ejemplo: quien decide solo cuenta con lo que el
    solicitante escriba, así que conviene decirle exactamente qué escribir.
    """
    filas = await obtener_todos(
        """
        select categoria_id, categoria_codigo, categoria_nombre, categoria_descripcion,
               categoria_ayuda, categoria_orden,
               tipo_id, tipo_codigo, tipo_nombre, tipo_descripcion,
               requiere_adjunto, requiere_justificacion, remunerado, descuenta_vacaciones,
               max_dias, max_horas, guia_ejemplo, guia_adjuntos
        from public.v_catalogo_permisos
        order by categoria_orden, tipo_orden
        """
    )
    mandato = await obtener_uno(
        "select valor from public.app_config where clave = 'mandato_descripcion'"
    )

    pilares: list[dict] = []
    for f in filas:
        if not pilares or pilares[-1]["codigo"] != f["categoria_codigo"]:
            pilares.append({
                "id": f["categoria_id"],
                "codigo": f["categoria_codigo"],
                "nombre": f["categoria_nombre"],
                "descripcion": f["categoria_descripcion"],
                "ayuda": f["categoria_ayuda"],
                "subtipos": [],
            })
        pilares[-1]["subtipos"].append({
            "id": f["tipo_id"],
            "codigo": f["tipo_codigo"],
            "nombre": f["tipo_nombre"],
            "descripcion": f["tipo_descripcion"],
            "requiere_adjunto": f["requiere_adjunto"],
            "requiere_justificacion": f["requiere_justificacion"],
            "remunerado": f["remunerado"],
            "descuenta_vacaciones": f["descuenta_vacaciones"],
            "max_dias": f["max_dias"],
            "max_horas": f["max_horas"],
            "guia_ejemplo": f["guia_ejemplo"],
            "guia_adjuntos": f["guia_adjuntos"],
        })

    return {"mandato": mandato["valor"] if mandato else "", "pilares": pilares}


@router.get("/catalogos/companeros")
async def companeros(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Quién puede cubrir la ausencia: el equipo del mismo jefe o departamento."""
    return await obtener_todos(
        """
        select id, nombre, cargo
        from public.users
        where activo and id <> %(yo)s
          and (
            (%(jefe)s::uuid is not null and jefe_id = %(jefe)s)
            or (%(depto)s::text is not null and departamento = %(depto)s)
          )
        order by nombre
        limit 100
        """,
        {"yo": usuario["id"], "jefe": usuario["jefe_id"], "depto": usuario["departamento"]},
    )


@router.get("/calendario")
async def calendario(
    usuario: Annotated[dict, Depends(usuario_actual)],
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict]:
    """Ausencias del equipo en el rango, para no dejar un puesto descubierto.

    Entre compañeros se ve quién falta y cuándo, nunca el motivo detallado:
    la categoría de un permiso médico es un dato de salud (LOPDP Art. 4).
    """
    if usuario["rol"] in ("rrhh", "admin"):
        alcance, parametros = "true", {}
    else:
        alcance = """(
            c.jefe_id = %(jefe)s
            or c.user_id = %(yo)s
            or c.jefe_id = %(yo)s
            or c.departamento = %(depto)s
        )"""
        parametros = {"jefe": usuario["jefe_id"], "yo": usuario["id"],
                      "depto": usuario["departamento"]}

    parametros |= {
        "desde": desde or date.today().replace(day=1),
        "hasta": hasta or (date.today() + timedelta(days=90)),
    }

    return await obtener_todos(
        f"""
        select c.request_id, c.folio, c.user_id, c.nombre, c.departamento,
               c.fecha_inicio, c.fecha_fin, c.estado, c.motivo_general,
               c.reemplazo_nombre
        from public.v_calendario_equipo c
        where {alcance}
          and c.fecha_fin >= %(desde)s and c.fecha_inicio <= %(hasta)s
        order by c.fecha_inicio
        """,
        parametros,
    )


@router.get("/jefe/calendario-equipo")
async def calendario_equipo(
    usuario: Annotated[dict, Depends(exigir_rol("jefe", "rrhh", "admin"))],
    desde: date | None = None,
    hasta: date | None = None,
    departamento: str | None = None,
) -> dict:
    """Calendario del equipo a cargo, mes a mes, para planificar la cobertura.

    Un jefe ve a sus reportes directos. Talento Humano y administración ven
    a todos, con filtro por departamento.

    Se entrega «Vacaciones» o «Permiso», nunca el subtipo: que alguien esté
    en cita médica es un dato de salud (LOPDP Art. 4) y no corresponde
    exhibirlo en una grilla mensual. El jefe sí lo ve en la solicitud que él
    mismo autoriza, que es donde tiene sentido.
    """
    inicio = desde or date.today().replace(day=1)
    fin = hasta or (inicio + timedelta(days=120))

    if usuario["rol"] == "jefe":
        alcance = "c.jefe_id = %(yo)s"
        parametros: dict = {"yo": usuario["id"]}
    else:
        alcance = "(%(depto)s::text is null or c.departamento = %(depto)s)"
        parametros = {"depto": departamento}

    ausencias = await obtener_todos(
        f"""
        select c.request_id, c.folio, c.user_id, c.nombre, c.cargo, c.departamento,
               c.fecha_inicio, c.fecha_fin, c.hora_inicio, c.hora_fin,
               c.dias_solicitados, c.estado, c.motivo_general,
               c.reemplazo_nombre, c.ajustada_en
        from public.v_calendario_equipo c
        where {alcance}
          and c.fecha_fin >= %(desde)s and c.fecha_inicio <= %(hasta)s
        order by c.fecha_inicio, c.nombre
        """,
        parametros | {"desde": inicio, "hasta": fin},
    )

    # El equipo completo, aunque nadie falte: un calendario que solo muestra
    # a los ausentes no deja ver quién queda disponible.
    equipo = await obtener_todos(
        """
        select id, nombre, cargo, departamento
        from public.users
        where activo and (
            (%(rol)s = 'jefe' and jefe_id = %(yo)s)
            or (%(rol)s <> 'jefe' and (%(depto)s::text is null or departamento = %(depto)s))
        )
        order by nombre
        """,
        {"rol": usuario["rol"], "yo": usuario["id"], "depto": departamento},
    )

    dias_libres = await obtener_todos(
        """select fecha, nombre from public.feriados
           where activo and fecha between %s and %s order by fecha""",
        (inicio, fin),
    )

    return {
        "desde": str(inicio),
        "hasta": str(fin),
        "equipo": [{**p, "id": str(p["id"])} for p in equipo],
        "ausencias": [
            {**a, "request_id": str(a["request_id"]), "user_id": str(a["user_id"]),
             "dias_solicitados": float(a["dias_solicitados"]),
             "hora_inicio": str(a["hora_inicio"])[:5] if a["hora_inicio"] else None,
             "hora_fin": str(a["hora_fin"])[:5] if a["hora_fin"] else None}
            for a in ausencias
        ],
        "feriados": [{"fecha": str(f["fecha"]), "nombre": f["nombre"]} for f in dias_libres],
    }


@router.get("/catalogos/feriados")
async def feriados(_: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Feriados futuros: el calendario los marca para que no cuenten días."""
    return await obtener_todos(
        """select fecha, nombre from public.feriados
           where activo and fecha >= current_date - 30 order by fecha"""
    )


# --------------------------------------------------------- previsualización
@router.post("/solicitudes/previsualizar")
async def previsualizar(
    datos: Previsualizacion, usuario: Annotated[dict, Depends(usuario_actual)]
) -> dict:
    """Días, saldo, avisos y rango corregido ANTES de enviar la solicitud."""
    try:
        fila = await obtener_uno(
            "select public.previsualizar_solicitud(%s, %s, %s, %s, %s) as resultado",
            (usuario["id"], datos.tipo, datos.fecha_inicio, datos.fecha_fin,
             datos.permission_type_id),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    return fila["resultado"] if fila else {}


# ------------------------------------------------------------------ envío
@router.post("/solicitudes", status_code=status.HTTP_201_CREATED)
async def crear_solicitud(
    datos: NuevaSolicitud, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)]
) -> dict:
    """Crea la solicitud con sus adjuntos y su firma en una sola transacción.

    La base valida en conjunto al confirmar: si el tipo de permiso exige
    respaldo o firma y no llegaron, se rechaza todo, no queda a medias.
    """
    firma = None
    if datos.firmar:
        firma = await obtener_uno(
            "select id, hash_sha256 from public.signatures where user_id = %s and activa",
            (usuario["id"],),
        )

    try:
        async with conexion() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into public.requests
                        (id, user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                         hora_inicio, hora_fin, descripcion, justificacion,
                         bloque_menor_justificado)
                    values (%(id)s, %(user_id)s, %(tipo)s, %(pt)s, %(inicio)s, %(fin)s,
                            %(h_ini)s, %(h_fin)s, %(desc)s, %(just)s, %(excepcion)s)
                    returning id, folio, estado, dias_solicitados, horas_solicitadas,
                              fines_semana, es_adelanto, saldo_al_solicitar, created_at
                    """,
                    {
                        "id": datos.id, "user_id": usuario["id"], "tipo": datos.tipo,
                        "pt": datos.permission_type_id, "inicio": datos.fecha_inicio,
                        "fin": datos.fecha_fin, "h_ini": datos.hora_inicio,
                        "h_fin": datos.hora_fin, "desc": datos.descripcion,
                        "just": datos.justificacion,
                        "excepcion": datos.bloque_menor_justificado,
                    },
                )
                creada = await cur.fetchone()

                for adjunto in datos.adjuntos:
                    await cur.execute(
                        """
                        insert into public.request_attachments
                            (request_id, storage_path, nombre_archivo, mime_type,
                             tamano_bytes, hash_sha256, subido_por)
                        values (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (datos.id, adjunto.storage_path, adjunto.nombre_archivo,
                         adjunto.mime_type, adjunto.tamano_bytes, adjunto.hash_sha256,
                         usuario["id"]),
                    )

                if firma:
                    await cur.execute(
                        """
                        insert into public.request_signatures
                            (request_id, user_id, rol_firma, signature_id, hash_sha256, ip, user_agent)
                        values (%s, %s, 'solicitante', %s, %s, %s, %s)
                        """,
                        (datos.id, usuario["id"], firma["id"], firma["hash_sha256"],
                         request.headers.get("x-forwarded-for", "").split(",")[0].strip() or None,
                         (request.headers.get("user-agent") or "")[:500]),
                    )
    except (pg.Error, Exception) as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "solicitud_enviada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="requests", entidad_id=str(datos.id),
                    detalle={"tipo": datos.tipo, "dias": float(creada["dias_solicitados"])})

    # El correo al jefe va en segundo plano: el SMTP no debe hacer esperar al empleado
    completa = await obtener_uno(
        """
        select r.id, r.tipo, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
               r.dias_solicitados, r.descripcion, r.justificacion, r.es_adelanto, r.jefe_token,
               u.nombre as empleado, pt.nombre as categoria,
               j.email as jefe_email, j.nombre as jefe_nombre
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.users j on j.id = r.jefe_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        where r.id = %s
        """,
        (datos.id,),
    )
    if completa and completa["jefe_email"]:
        tareas.add_task(
            notificaciones.avisar_al_jefe,
            {"email": completa["jefe_email"], "nombre": completa["jefe_nombre"]},
            completa,
        )
    elif completa:
        log.warning("La solicitud %s no tiene jefe asignado: nadie recibió el aviso", datos.id)

    return {
        "id": str(creada["id"]),
        "folio": creada["folio"],
        "estado": creada["estado"],
        "dias_solicitados": float(creada["dias_solicitados"]),
        "horas_solicitadas": float(creada["horas_solicitadas"]) if creada["horas_solicitadas"] else None,
        "fines_semana": creada["fines_semana"],
        "es_adelanto": creada["es_adelanto"],
        "mensaje": f"Solicitud Nº {creada['folio']} enviada a su jefe inmediato.",
    }


# --------------------------------------------------------------- consultas
@router.get("/solicitudes/mias")
async def mis_solicitudes(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    return await obtener_todos(
        """
        select r.id, r.folio, r.tipo, pt.nombre as categoria, r.fecha_inicio, r.fecha_fin,
               r.hora_inicio, r.hora_fin, r.dias_solicitados, r.horas_solicitadas,
               r.descripcion, r.justificacion, r.estado, r.es_adelanto,
               r.motivo_rechazo, r.rechazado_en_etapa, r.anulacion_motivo, r.created_at,
               r.qr_hash, r.qr_emitido_en, r.qr_usado_en,
               j.nombre as jefe, rp.nombre as reemplazo,
               r.jefe_aprobado_en, r.rrhh_aprobado_en,
               (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
               (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
        from public.requests r
        left join public.users j on j.id = r.jefe_id
        left join public.users rp on rp.id = r.reemplazo_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        where r.user_id = %s
        order by r.created_at desc
        limit 100
        """,
        (usuario["id"],),
    )


class Anulacion(BaseModel):
    motivo: str | None = Field(None, max_length=300)


@router.post("/solicitudes/{solicitud_id}/cancelar")
async def cancelar(
    solicitud_id: uuid.UUID, datos: Anulacion, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Cancelar o pedir anulación, según en qué punto esté la solicitud.

    Mientras espera aprobación no se ha descontado nada: se cancela y listo.
    Una vez aprobada ya consumió saldo y tiene un QR emitido, así que
    deshacerla necesita el visto bueno de Talento Humano.
    """
    actual = await obtener_uno(
        "select estado::text, folio from public.requests where id = %s and user_id = %s",
        (solicitud_id, usuario["id"]),
    )
    if actual is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"mensaje": "No se encontró esa solicitud entre las suyas."})

    if actual["estado"] in ("pendiente_jefe", "pendiente_rrhh"):
        nuevo, accion, mensaje = "cancelado", "solicitud_cancelada", "Solicitud cancelada."
    elif actual["estado"] == "aprobado":
        if not (datos.motivo or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"mensaje": "Indique por qué necesita anular una solicitud ya aprobada."},
            )
        nuevo, accion = "pendiente_anulacion", "anulacion_solicitada"
        mensaje = "Su pedido de anulación pasó a Talento Humano."
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": f"Una solicitud en estado «{actual['estado']}» ya no se puede anular."},
        )

    try:
        fila = await obtener_uno(
            """update public.requests
                  set estado = %s, anulacion_motivo = coalesce(%s, anulacion_motivo)
                where id = %s returning id, estado::text""",
            (nuevo, (datos.motivo or "").strip() or None, solicitud_id),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, accion, user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="requests", entidad_id=str(solicitud_id),
                    detalle={"folio": actual["folio"], "motivo": datos.motivo})
    return {"id": str(fila["id"]), "estado": fila["estado"], "mensaje": mensaje}


# ---------------------------------------------------------------- adjuntos
@router.post("/solicitudes/adjuntos")
async def subir(
    request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
    solicitud_id: uuid.UUID,
    archivo: UploadFile = File(...),
) -> dict:
    """Sube el respaldo a Storage y devuelve la ruta para enviarla con la solicitud.

    Se valida aquí y otra vez en la base: el tamaño y el tipo no dependen
    de lo que declare el navegador.
    """
    contenido = await archivo.read()

    if len(contenido) == 0:
        raise HTTPException(status_code=422, detail={"mensaje": "El archivo está vacío."})
    if len(contenido) > TAMANO_MAXIMO:
        raise HTTPException(status_code=413,
                            detail={"mensaje": "Cada archivo debe pesar menos de 10 MB."})
    if archivo.content_type not in MIMES_PERMITIDOS:
        raise HTTPException(status_code=422,
                            detail={"mensaje": "Solo se admiten imágenes (JPG, PNG, WebP, HEIC) o PDF."})

    ruta = f"{usuario['id']}/{solicitud_id}/{uuid.uuid4().hex}-{archivo.filename[:60]}"
    await subir_adjunto(ruta, contenido, archivo.content_type)

    await registrar(request, "adjunto_subido", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="request_attachments",
                    entidad_id=str(solicitud_id), detalle={"archivo": archivo.filename})

    return {
        "storage_path": ruta,
        "nombre_archivo": archivo.filename,
        "mime_type": archivo.content_type,
        "tamano_bytes": len(contenido),
        "hash_sha256": hashlib.sha256(contenido).hexdigest(),
    }
