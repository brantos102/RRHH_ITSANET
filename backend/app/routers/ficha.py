"""Ficha personal: lo que cada quien corrige y lo que Talento Humano valida.

Un teléfono cambia, una dirección cambia, el contacto de emergencia cambia.
Obligar a que Talento Humano teclee cada uno de esos datos para 351 personas
es un cuello de botella sin ningún beneficio: nadie conoce mejor su propio
número. Pero el nombre, el correo o el estado civil sí deben validarse,
porque de ahí salen documentos.

Los tres niveles —libre, revisado y bloqueado— viven en la tabla
`campos_ficha`, y quien decide es la base: una comprobación que solo esté
en este archivo la puede saltar cualquier cliente alterado.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir

router = APIRouter(tags=["Ficha personal"])

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class CambiosLibres(BaseModel):
    """Solo campos de nivel «libre». La base rechaza cualquier otro."""
    telefono: str | None = Field(None, max_length=20)
    telefono_alternativo: str | None = Field(None, max_length=20)
    direccion: str | None = Field(None, max_length=200)
    tipo_sangre: str | None = Field(None, max_length=3)
    foto_url: str | None = Field(None, max_length=500)


class SolicitudCambio(BaseModel):
    campo: str = Field(..., max_length=40)
    valor: str = Field(..., min_length=1, max_length=200)
    motivo: str | None = Field(None, max_length=300)


class DecisionCambio(BaseModel):
    accion: Literal["aprobar", "rechazar"]
    motivo: str | None = Field(None, max_length=300)


@router.get("/mi-ficha")
async def mi_ficha(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """La ficha completa, con qué se puede tocar y qué no, y por qué."""
    persona = await obtener_uno(
        """select u.cedula, u.nombre, u.email::text as email, u.telefono,
                  u.telefono_alternativo, u.direccion, u.ciudad, u.provincia,
                  u.tipo_sangre, u.foto_url, u.fecha_nacimiento, u.estado_civil::text
                    as estado_civil,
                  u.fecha_ingreso, u.cargo, u.departamento, u.bodega, u.cliente,
                  u.centro_costo, u.dias_vacaciones, u.tiene_discapacidad,
                  u.porcentaje_discapacidad, coalesce(u.region, 'sierra') as region,
                  r.nombre as region_nombre, r.sede as region_sede,
                  j.nombre as jefe_nombre
             from public.users u
             left join public.regiones r on r.codigo = coalesce(u.region, 'sierra')
             left join public.users j on j.id = u.jefe_id
            where u.id = %s""",
        (usuario["id"],),
    )
    campos = await obtener_todos(
        "select campo, etiqueta, nivel, ayuda from public.campos_ficha order by orden"
    )
    contactos = await obtener_todos(
        """select id, nombre, parentesco::text as parentesco, telefono, es_principal
             from public.emergency_contacts where user_id = %s order by es_principal desc""",
        (usuario["id"],),
    )
    pendientes = await obtener_todos(
        """select c.id, c.campo, f.etiqueta, c.valor_anterior, c.valor_nuevo,
                  c.estado, c.motivo_rechazo, c.created_at
             from public.cambios_ficha c
             join public.campos_ficha f on f.campo = c.campo
            where c.user_id = %s order by c.created_at desc limit 20""",
        (usuario["id"],),
    )
    return {
        "persona": {**persona, "dias_vacaciones": float(persona["dias_vacaciones"] or 0)},
        "campos": campos,
        "contactos_emergencia": [{**c, "id": str(c["id"])} for c in contactos],
        "cambios": [{**c, "id": int(c["id"])} for c in pendientes],
    }


@router.patch("/mi-ficha")
async def corregir_ficha(
    datos: CambiosLibres, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Los datos que la persona corrige sola, sin esperar a nadie."""
    cambios = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "No hay nada que cambiar."},
        )

    try:
        await obtener_uno(
            "select public.actualizar_ficha_libre(%s, %s::jsonb) is not null as ok",
            (usuario["id"], json.dumps(cambios)),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_actualizada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campos": list(cambios)})
    return {"mensaje": "Sus datos quedaron actualizados."}


@router.post("/mi-ficha/cambios", status_code=status.HTTP_201_CREATED)
async def pedir_cambio(
    datos: SolicitudCambio, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Lo que Talento Humano debe validar antes de que rija."""
    try:
        fila = await obtener_uno(
            "select public.solicitar_cambio_ficha(%s, %s, %s, %s) as id",
            (usuario["id"], datos.campo, datos.valor, datos.motivo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_solicitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campo": datos.campo})
    return {
        "id": int(fila["id"]),
        "mensaje": "Su solicitud quedó registrada. Talento Humano la revisará; "
                   "mientras tanto sigue vigente el dato anterior.",
    }


@router.get("/rrhh/cambios-ficha")
async def cambios_pendientes(usuario: RRHH) -> list[dict]:
    """Bandeja de Talento Humano, acotada a su región."""
    if usuario["rol"] == "admin":
        filtro, parametros = "true", ()
    else:
        filtro, parametros = "region = %s", (usuario.get("region") or "sierra",)

    filas = await obtener_todos(
        f"""select id, user_id, cedula, persona, departamento, ciudad, region,
                   campo, etiqueta, valor_anterior, valor_nuevo, motivo, created_at
              from public.v_cambios_ficha_pendientes where {filtro}""",
        parametros,
    )
    return [{**f, "id": int(f["id"]), "user_id": str(f["user_id"])} for f in filas]


@router.post("/rrhh/cambios-ficha/{cambio_id}")
async def resolver_cambio(
    cambio_id: int, datos: DecisionCambio, request: Request, usuario: RRHH,
) -> dict:
    if datos.accion == "rechazar" and len((datos.motivo or "").strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Indique por qué se rechaza: la persona debe saber qué corregir."},
        )
    try:
        fila = await obtener_uno(
            "select (public.resolver_cambio_ficha(%s, %s, %s, %s)).campo as campo",
            (cambio_id, datos.accion == "aprobar", usuario["id"], datos.motivo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_resuelto", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"cambio": cambio_id, "accion": datos.accion})
    return {
        "mensaje": ("Cambio aplicado." if datos.accion == "aprobar"
                    else "Cambio rechazado. Se le avisó a la persona."),
        "campo": fila["campo"],
    }
