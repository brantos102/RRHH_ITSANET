"""Sedes y regiones, administradas desde el sistema (Administración › Sedes)."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from ..audit import registrar
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir
from ..reglas import sedes

router = APIRouter(tags=["Sedes y regiones"])
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]
Natural = Literal["costa", "sierra", "amazonia", "insular"]


class NuevaSede(BaseModel):
    sede: str = Field(..., min_length=3, max_length=60, description="Ciudad de la sede")
    nombre: str | None = Field(None, max_length=80)
    descripcion: str | None = Field(None, max_length=300)
    regiones_naturales: list[Natural] = []
    correo: EmailStr | None = None


class CambioSede(BaseModel):
    sede: str | None = Field(None, min_length=3, max_length=60)
    nombre: str | None = Field(None, max_length=80)
    descripcion: str | None = Field(None, max_length=300)
    regiones_naturales: list[Natural] | None = None
    activo: bool | None = None
    correo: EmailStr | Literal[""] | None = None


class Ciudad(BaseModel):
    ciudad: str = Field(..., min_length=3, max_length=80)
    region: str = Field(..., max_length=20, description="Código de la sede que la atiende")
    provincia: str | None = Field(None, max_length=60)
    region_natural: Natural | None = None


@router.get("/catalogos/sedes")
async def catalogo(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Las sedes activas, para los selectores de cualquier pantalla."""
    return await sedes.catalogo()


@router.get("/admin/sedes")
async def ver(usuario: RRHH) -> dict:
    return await sedes.resumen()


@router.post("/admin/sedes", status_code=201)
async def crear(datos: NuevaSede, request: Request, usuario: RRHH) -> dict:
    try:
        codigo = await sedes.crear_sede(datos.sede, datos.nombre or "", datos.descripcion,
                                        list(datos.regiones_naturales), datos.correo)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "sede_creada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="regiones", entidad_id=codigo, detalle=datos.model_dump(mode="json"))
    return {"codigo": codigo,
            "mensaje": f"Sede {datos.sede} creada. Asígnele ciudades y quién firma por Talento Humano."}


@router.patch("/admin/sedes/{codigo}")
async def cambiar(codigo: str, datos: CambioSede, request: Request, usuario: RRHH) -> dict:
    cambios = datos.model_dump(exclude_unset=True, mode="json")
    if not cambios:
        raise HTTPException(status_code=422, detail={"mensaje": "No indicó ningún cambio."})
    try:
        await sedes.cambiar_sede(codigo, cambios)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "sede_modificada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="regiones", entidad_id=codigo, detalle=cambios)
    return {"mensaje": "Sede actualizada."}


@router.post("/admin/ciudades")
async def guardar_ciudad(datos: Ciudad, request: Request, usuario: RRHH) -> dict:
    try:
        r = await sedes.guardar_ciudad(datos.ciudad, datos.region, datos.provincia,
                                       datos.region_natural)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "ciudad_guardada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="ciudades_region", entidad_id=sedes.ciudad_normal(datos.ciudad),
                    detalle={**datos.model_dump(mode="json"), **r})
    extra = ""
    if r["personas"]:
        extra = (f" {r['personas']} persona(s) pasaron a esa sede"
                 + (f" con {r['tramites']} trámite(s) en curso." if r["tramites"] else "."))
    return {**r, "mensaje": f"Ciudad guardada.{extra}"}


@router.delete("/admin/ciudades/{ciudad}")
async def quitar_ciudad(ciudad: str, request: Request, usuario: RRHH) -> dict:
    try:
        await sedes.quitar_ciudad(ciudad)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "ciudad_quitada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="ciudades_region", entidad_id=sedes.ciudad_normal(ciudad))
    return {"mensaje": "Ciudad quitada."}
