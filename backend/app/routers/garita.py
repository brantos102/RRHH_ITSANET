"""Control de acceso en garita: validación de QR y registro de visitas.

El guardia trabaja de pie, con una mano y con prisa. La API responde con un
veredicto claro (autorizado / denegado) y el motivo en una frase, para que
la pantalla se lea de un vistazo.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from ..audit import ip_del_cliente, registrar
from ..cedula import es_cedula_valida, normalizar_cedula
from ..db import conexion, obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..errores import traducir

log = logging.getLogger("rrhh.garita")
router = APIRouter(prefix="/garita", tags=["Garita"])

Guardia = Annotated[dict, Depends(exigir_rol("guardia", "rrhh", "admin"))]


class LecturaQR(BaseModel):
    codigo: str = Field(..., max_length=200)

    @field_validator("codigo")
    @classmethod
    def limpiar(cls, v: str) -> str:
        return v.strip()


class NuevoVisitante(BaseModel):
    cedula: str
    nombre: str = Field(..., min_length=3, max_length=120)
    empresa: str | None = Field(None, max_length=120)
    telefono: str | None = Field(None, max_length=20)
    motivo_visita: str = Field(..., min_length=3, max_length=200)
    a_quien_visita: uuid.UUID | None = None
    a_quien_visita_texto: str | None = Field(None, max_length=120)

    @field_validator("cedula")
    @classmethod
    def validar(cls, v: str) -> str:
        limpia = normalizar_cedula(v)
        if not es_cedula_valida(limpia):
            raise ValueError("La cédula del visitante no es válida.")
        return limpia


# --------------------------------------------------------------- validación
@router.post("/validar-qr")
async def validar_qr(lectura: LecturaQR, request: Request, guardia: Guardia) -> dict:
    """Valida el código y deja constancia del intento, salga como salga.

    Todo intento queda en la bitácora, incluidos los denegados: un código
    que no existe puede ser un error de lectura o alguien probando suerte.
    """
    hoy = date.today()

    try:
        codigo = uuid.UUID(lectura.codigo)
    except ValueError:
        await registrar(request, "garita_qr_ilegible", user_id=str(guardia["id"]),
                        cedula=guardia["cedula"], detalle={"leido": lectura.codigo[:80]})
        await _registrar_acceso(request, guardia, autorizado=False,
                                observacion="Código ilegible", cedula=None)
        return {"autorizado": False, "motivo": "El código no es válido. Pida el QR del sistema."}

    solicitud = await obtener_uno(
        """
        select r.id, r.folio, r.estado, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
               r.qr_expira_en, r.qr_usado_en, r.tipo,
               u.id as user_id, u.cedula, u.nombre, u.cargo, u.departamento, u.telefono,
               pt.nombre as categoria,
               j.nombre as autorizo_jefe, h.nombre as autorizo_rrhh,
               (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.users j on j.id = r.jefe_aprobado_por
        left join public.users h on h.id = r.rrhh_aprobado_por
        left join public.permission_types pt on pt.id = r.permission_type_id
        where r.qr_hash = %s
        """,
        (codigo,),
    )

    if solicitud is None:
        await _registrar_acceso(request, guardia, autorizado=False,
                                observacion="Código no encontrado", cedula=None)
        return {"autorizado": False, "motivo": "Este código no corresponde a ninguna autorización."}

    base = {
        "folio": solicitud["folio"],
        "nombre": solicitud["nombre"],
        "cedula": solicitud["cedula"],
        "cargo": solicitud["cargo"],
        "departamento": solicitud["departamento"],
        "tipo": "Vacaciones" if solicitud["tipo"] == "vacacion" else (solicitud["categoria"] or "Permiso"),
        "desde": solicitud["fecha_inicio"],
        "hasta": solicitud["fecha_fin"],
        "hora_inicio": str(solicitud["hora_inicio"])[:5] if solicitud["hora_inicio"] else None,
        "hora_fin": str(solicitud["hora_fin"])[:5] if solicitud["hora_fin"] else None,
        "autorizo_jefe": solicitud["autorizo_jefe"],
        "autorizo_rrhh": solicitud["autorizo_rrhh"],
        "firmas": solicitud["firmas"],
    }

    # Motivos de denegación, del más grave al más leve
    motivo = None
    if solicitud["estado"] == "cancelado":
        motivo = "Esta autorización fue anulada."
    elif solicitud["estado"] != "aprobado":
        motivo = "Esta solicitud aún no está aprobada."
    elif not (solicitud["fecha_inicio"] <= hoy <= solicitud["fecha_fin"]):
        motivo = (f"Fuera de fecha: la autorización rige del "
                  f"{solicitud['fecha_inicio']:%d/%m/%Y} al {solicitud['fecha_fin']:%d/%m/%Y}.")

    if motivo:
        await _registrar_acceso(request, guardia, autorizado=False, observacion=motivo,
                                cedula=solicitud["cedula"], user_id=str(solicitud["user_id"]),
                                request_id=str(solicitud["id"]))
        return {"autorizado": False, "motivo": motivo, **base}

    # Autorizado: se registra la salida y se cuenta el uso del código
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """update public.requests
                      set qr_usos = qr_usos + 1, qr_usado_en = coalesce(qr_usado_en, now())
                    where id = %s""",
                (solicitud["id"],),
            )
            await cur.execute(
                """
                insert into public.access_logs
                    (user_id, cedula, request_id, tipo_acceso, autorizado, guardia_id, ip, user_agent)
                values (%s, %s, %s, 'salida_empleado', true, %s, %s, %s)
                """,
                (solicitud["user_id"], solicitud["cedula"], solicitud["id"], guardia["id"],
                 ip_del_cliente(request), (request.headers.get("user-agent") or "")[:500]),
            )

    await registrar(request, "garita_salida_autorizada", user_id=str(guardia["id"]),
                    cedula=guardia["cedula"], entidad="requests", entidad_id=str(solicitud["id"]),
                    detalle={"empleado": solicitud["nombre"], "folio": solicitud["folio"]})

    return {
        "autorizado": True,
        "motivo": "Salida autorizada.",
        "ya_usado_antes": solicitud["qr_usado_en"] is not None,
        **base,
    }


async def _registrar_acceso(request: Request, guardia: dict, *, autorizado: bool,
                            observacion: str, cedula: str | None,
                            user_id: str | None = None, request_id: str | None = None) -> None:
    await obtener_uno(
        """
        insert into public.access_logs
            (user_id, cedula, request_id, tipo_acceso, autorizado, observacion,
             guardia_id, ip, user_agent)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (user_id, cedula, request_id,
         "salida_empleado" if autorizado else "acceso_denegado",
         autorizado, observacion, guardia["id"],
         ip_del_cliente(request), (request.headers.get("user-agent") or "")[:500]),
    )


# ------------------------------------------------------------ panel del día
@router.get("/hoy")
async def personal_de_hoy(guardia: Guardia) -> dict:
    """Quién tiene autorización vigente y quién la tiene en trámite."""
    filas = await obtener_todos(
        """
        select r.id, r.folio, r.estado::text, r.tipo::text, pt.nombre as categoria,
               r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin, r.qr_usado_en,
               u.cedula, u.nombre, u.departamento, u.cargo
        from public.requests r
        join public.users u on u.id = r.user_id
        left join public.permission_types pt on pt.id = r.permission_type_id
        where r.estado in ('aprobado', 'pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion')
          and current_date between r.fecha_inicio and r.fecha_fin
        order by r.estado, u.nombre
        """
    )
    normalizadas = [
        {**f, "id": str(f["id"]),
         "hora_inicio": str(f["hora_inicio"])[:5] if f["hora_inicio"] else None,
         "hora_fin": str(f["hora_fin"])[:5] if f["hora_fin"] else None}
        for f in filas
    ]
    return {
        "aprobadas": [f for f in normalizadas if f["estado"] == "aprobado"],
        "en_tramite": [f for f in normalizadas if f["estado"] != "aprobado"],
    }


@router.get("/accesos")
async def accesos_recientes(guardia: Guardia, limite: int = 40) -> list[dict]:
    return await obtener_todos(
        """
        select a.id, a.tipo_acceso::text, a.autorizado, a.observacion, a.created_at,
               coalesce(u.nombre, v.nombre) as persona,
               coalesce(a.cedula, u.cedula, v.cedula) as cedula,
               g.nombre as guardia
        from public.access_logs a
        left join public.users u on u.id = a.user_id
        left join public.visitors v on v.id = a.visitor_id
        left join public.users g on g.id = a.guardia_id
        order by a.created_at desc
        limit %s
        """,
        (min(limite, 200),),
    )


# ---------------------------------------------------------------- visitantes
@router.post("/visitantes", status_code=status.HTTP_201_CREATED)
async def registrar_visitante(datos: NuevoVisitante, request: Request, guardia: Guardia) -> dict:
    try:
        async with conexion() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    insert into public.visitors
                        (cedula, nombre, empresa, telefono, motivo_visita,
                         a_quien_visita, a_quien_visita_texto, registrado_por)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    returning id, nombre, ingreso_en
                    """,
                    (datos.cedula, datos.nombre.strip(), datos.empresa, datos.telefono,
                     datos.motivo_visita.strip(), datos.a_quien_visita,
                     datos.a_quien_visita_texto, guardia["id"]),
                )
                visitante = await cur.fetchone()

                await cur.execute(
                    """
                    insert into public.access_logs
                        (visitor_id, cedula, tipo_acceso, autorizado, guardia_id, ip, user_agent)
                    values (%s, %s, 'ingreso_visita', true, %s, %s, %s)
                    """,
                    (visitante["id"], datos.cedula, guardia["id"],
                     ip_del_cliente(request), (request.headers.get("user-agent") or "")[:500]),
                )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "garita_ingreso_visita", user_id=str(guardia["id"]),
                    cedula=guardia["cedula"], entidad="visitors", entidad_id=str(visitante["id"]),
                    detalle={"visitante": datos.nombre, "cedula": datos.cedula})

    return {"id": str(visitante["id"]), "nombre": visitante["nombre"],
            "ingreso_en": visitante["ingreso_en"],
            "mensaje": f"Ingreso registrado: {visitante['nombre']}."}


@router.get("/visitantes/dentro")
async def visitantes_dentro(guardia: Guardia) -> list[dict]:
    return await obtener_todos(
        """
        select v.id, v.cedula, v.nombre, v.empresa, v.motivo_visita, v.telefono,
               coalesce(u.nombre, v.a_quien_visita_texto) as visita_a, v.ingreso_en
        from public.visitors v
        left join public.users u on u.id = v.a_quien_visita
        where v.salida_en is null
        order by v.ingreso_en desc
        """
    )


@router.post("/visitantes/{visitante_id}/salida")
async def registrar_salida(visitante_id: uuid.UUID, request: Request, guardia: Guardia) -> dict:
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """update public.visitors set salida_en = now()
                    where id = %s and salida_en is null
                    returning id, nombre, cedula, ingreso_en, salida_en""",
                (visitante_id,),
            )
            visitante = await cur.fetchone()
            if visitante is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"mensaje": "No hay un visitante con esa ficha todavía dentro."},
                )
            await cur.execute(
                """
                insert into public.access_logs
                    (visitor_id, cedula, tipo_acceso, autorizado, guardia_id, ip, user_agent)
                values (%s, %s, 'salida_visita', true, %s, %s, %s)
                """,
                (visitante["id"], visitante["cedula"], guardia["id"],
                 ip_del_cliente(request), (request.headers.get("user-agent") or "")[:500]),
            )

    await registrar(request, "garita_salida_visita", user_id=str(guardia["id"]),
                    cedula=guardia["cedula"], entidad="visitors", entidad_id=str(visitante_id))

    minutos = int((visitante["salida_en"] - visitante["ingreso_en"]).total_seconds() // 60)
    return {"id": str(visitante["id"]),
            "mensaje": f"Salida registrada: {visitante['nombre']} ({minutos} min dentro)."}


@router.get("/buscar-anfitrion")
async def buscar_anfitrion(guardia: Guardia, q: str = "") -> list[dict]:
    """A quién visita: se busca por nombre o cédula mientras se escribe."""
    if len(q.strip()) < 2:
        return []
    return await obtener_todos(
        """select id, nombre, cargo, departamento
           from public.users
           where activo and (nombre ilike %(q)s or cedula like %(c)s)
           order by nombre limit 15""",
        {"q": f"%{q.strip()}%", "c": f"{normalizar_cedula(q)}%"},
    )
