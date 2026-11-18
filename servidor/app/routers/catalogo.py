"""Administración › Cargos y áreas, y Administración › Actualización masiva.

Lo que antes había que corregir en la base —cargos y áreas escritos de mil
formas, el cambio de área de cuarenta personas— se hace desde aquí, con
vista previa y con constancia de quién, cuándo y por qué.
"""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import obtener_todos
from ..deps import exigir_rol
from ..errores import traducir
from ..reglas import altas, catalogo, masivo

router = APIRouter(tags=["Catálogo y actualización masiva"])
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class Area(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)


class CambioArea(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=120)
    activo: bool | None = None


class Cargo(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)
    area_id: int | None = None


class CambioCargo(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=120)
    area_id: int | None = None
    mover_area: bool = False
    activo: bool | None = None


class Unificar(BaseModel):
    destino_id: int


class Aplicar(BaseModel):
    motivo: str = Field(..., min_length=10, max_length=300)


async def _hacer(request: Request, usuario: dict, accion: str, detalle: dict, corrutina):
    try:
        resultado = await corrutina
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, accion, user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="catalogo", detalle={**detalle, "resultado": resultado})
    return resultado


# ---------------------------------------------------------------- catálogo
@router.get("/admin/catalogo")
async def ver_catalogo(usuario: RRHH) -> dict:
    return await catalogo.resumen()


@router.post("/admin/catalogo/areas", status_code=201)
async def crear_area(datos: Area, request: Request, usuario: RRHH) -> dict:
    nuevo = await _hacer(request, usuario, "area_creada", datos.model_dump(), catalogo.crear_area(datos.nombre))
    return {"id": nuevo, "mensaje": f"Área «{datos.nombre.strip()}» creada."}


@router.patch("/admin/catalogo/areas/{area_id}")
async def cambiar_area(area_id: int, datos: CambioArea, request: Request, usuario: RRHH) -> dict:
    n = await _hacer(request, usuario, "area_modificada", {"id": area_id, **datos.model_dump()},
                     catalogo.cambiar_area(area_id, datos.nombre, datos.activo))
    return {"fichas": n, "mensaje": "Área actualizada." + (f" Cambió en {n} ficha(s)." if n else "")}


@router.post("/admin/catalogo/areas/{area_id}/unificar")
async def unificar_area(area_id: int, datos: Unificar, request: Request, usuario: RRHH) -> dict:
    n = await _hacer(request, usuario, "areas_unificadas", {"origen": area_id, "destino": datos.destino_id},
                     catalogo.unificar_areas(area_id, datos.destino_id))
    return {"fichas": n, "mensaje": f"Áreas unificadas. {n} ficha(s) pasaron al área de destino."}


@router.post("/admin/catalogo/cargos", status_code=201)
async def crear_cargo(datos: Cargo, request: Request, usuario: RRHH) -> dict:
    nuevo = await _hacer(request, usuario, "cargo_creado", datos.model_dump(),
                         catalogo.crear_cargo(datos.nombre, datos.area_id))
    return {"id": nuevo, "mensaje": f"Cargo «{datos.nombre.strip()}» creado."}


@router.patch("/admin/catalogo/cargos/{cargo_id}")
async def cambiar_cargo(cargo_id: int, datos: CambioCargo, request: Request, usuario: RRHH) -> dict:
    n = await _hacer(request, usuario, "cargo_modificado", {"id": cargo_id, **datos.model_dump()},
                     catalogo.cambiar_cargo(cargo_id, datos.nombre, datos.area_id, datos.mover_area, datos.activo))
    return {"fichas": n, "mensaje": "Cargo actualizado." + (f" Cambió en {n} ficha(s)." if n else "")}


@router.post("/admin/catalogo/cargos/{cargo_id}/unificar")
async def unificar_cargo(cargo_id: int, datos: Unificar, request: Request, usuario: RRHH) -> dict:
    n = await _hacer(request, usuario, "cargos_unificados", {"origen": cargo_id, "destino": datos.destino_id},
                     catalogo.unificar_cargos(cargo_id, datos.destino_id))
    return {"fichas": n, "mensaje": f"Cargos unificados. {n} ficha(s) pasaron al cargo de destino."}


@router.post("/admin/catalogo/incorporar")
async def incorporar(request: Request, usuario: RRHH) -> dict:
    """Agrega al catálogo lo que está en las fichas y no en el catálogo."""
    fuera = (await catalogo.resumen())["fuera_de_catalogo"]
    for f in fuera:
        await catalogo.asegurar(f["nombre"] if f["tipo"] == "cargo" else None,
                                f["area"] if f["tipo"] == "cargo" else f["nombre"])
    await registrar(request, "catalogo_incorporado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="catalogo", detalle={"agregados": len(fuera)})
    return {"mensaje": f"{len(fuera)} nombre(s) agregados al catálogo."}


# --------------------------------------------------------- carga masiva
@router.get("/admin/masivo/plantilla.xlsx", response_class=Response)
async def plantilla(request: Request, usuario: RRHH, area: str | None = None, sede: str | None = None) -> Response:
    contenido = await masivo.plantilla(area, sede)
    await registrar(request, "plantilla_masiva_descargada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"area": area, "sede": sede})
    return Response(contenido, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="actualizacion-masiva.xlsx"',
                             "Cache-Control": "no-store"})


@router.get("/admin/masivo/plantilla-altas.xlsx", response_class=Response)
async def plantilla_altas(request: Request, usuario: RRHH) -> Response:
    contenido = await altas.plantilla()
    await registrar(request, "plantilla_altas_descargada", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    return Response(contenido, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="personas-nuevas.xlsx"',
                             "Cache-Control": "no-store"})


async def _archivo(archivo: UploadFile) -> tuple[str, bytes]:
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=422, detail={"mensaje": "El archivo está vacío."})
    if len(contenido) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"mensaje": "El archivo debe pesar menos de 5 MB."})
    nombre = archivo.filename or "archivo.xlsx"
    if not nombre.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=422, detail={"mensaje": "Suba la plantilla en Excel (.xlsx) o CSV."})
    return nombre, contenido


@router.post("/admin/masivo/revisar-altas")
async def revisar_altas(request: Request, usuario: RRHH, archivo: UploadFile = File(...)) -> dict:
    nombre, contenido = await _archivo(archivo)
    try:
        r = await altas.revisar(nombre, contenido, str(usuario["id"]))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "altas_masivas_revisadas", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="cargas_masivas", entidad_id=r["folio"],
                    detalle={"filas": r["filas"], "altas": len(r["altas"]), "errores": len(r["errores"]),
                             "ya_registradas": r["ya_registradas"]})
    return r


@router.post("/admin/masivo/revisar")
async def revisar(request: Request, usuario: RRHH, archivo: UploadFile = File(...)) -> dict:
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=422, detail={"mensaje": "El archivo está vacío."})
    if len(contenido) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"mensaje": "El archivo debe pesar menos de 5 MB."})
    nombre = archivo.filename or "archivo.xlsx"
    if not nombre.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=422, detail={"mensaje": "Suba la plantilla en Excel (.xlsx) o CSV."})
    try:
        r = await masivo.revisar(nombre, contenido, str(usuario["id"]))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "carga_masiva_revisada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="cargas_masivas", entidad_id=r["folio"],
                    detalle={"filas": r["filas"], "cambios": len(r["cambios"]), "errores": len(r["errores"])})
    return r


@router.post("/admin/masivo/{folio}/aplicar")
async def aplicar(folio: str, datos: Aplicar, request: Request, usuario: RRHH) -> dict:
    from ..db import obtener_uno
    carga = await obtener_uno("SELECT tipo FROM cargas_masivas WHERE folio = %s", (folio,))
    if carga and carga["tipo"] == "altas":
        try:
            r = await altas.aplicar(folio, datos.motivo, str(usuario["id"]))
        except Exception as exc:  # noqa: BLE001
            raise traducir(exc) from exc
        await registrar(request, "altas_masivas_aplicadas", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                        entidad="cargas_masivas", entidad_id=folio, detalle={**r, "motivo": datos.motivo})
        return {**r, "mensaje": f"Carga {folio} aplicada: {r['personas']} persona(s) registrada(s)."
                + (f" {r['sin_correo']} sin correo: regístreselo en Usuarios para que puedan entrar."
                   if r["sin_correo"] else "")}
    try:
        r = await masivo.aplicar(folio, datos.motivo, str(usuario["id"]))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "carga_masiva_aplicada", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="cargas_masivas", entidad_id=folio, detalle={**r, "motivo": datos.motivo})
    return {**r, "mensaje": f"Carga {folio} aplicada: {r['cambios']} cambio(s) en {r['personas']} persona(s)."
            + (f" {r['cambian_de_sede']} cambiaron de sede, con sus trámites." if r["cambian_de_sede"] else "")}


@router.post("/admin/masivo/{folio}/descartar")
async def descartar(folio: str, usuario: RRHH) -> dict:
    try:
        await masivo.descartar(folio)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    return {"mensaje": "Carga descartada: no se cambió nada."}


@router.get("/admin/masivo")
async def historial(usuario: RRHH) -> list[dict]:
    filas = await obtener_todos(
        """SELECT c.folio, c.tipo, c.archivo, c.filas, c.estado, c.motivo, c.subido_en, c.aplicado_en, c.sha256,
                  JSON_LENGTH(c.cambios) AS cambios, s.nombre AS subido_por, a.nombre AS aplicado_por
             FROM cargas_masivas c LEFT JOIN users s ON s.id = c.subido_por
             LEFT JOIN users a ON a.id = c.aplicado_por
            ORDER BY c.subido_en DESC LIMIT 100""")
    return filas


@router.get("/admin/masivo/{folio}")
async def detalle(folio: str, usuario: RRHH) -> dict:
    from ..db import obtener_uno
    c = await obtener_uno("SELECT folio, estado, cambios, errores FROM cargas_masivas WHERE folio = %s", (folio,))
    if c is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Esa carga no existe."})
    leer = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
    return {"folio": c["folio"], "estado": c["estado"], "cambios": leer(c["cambios"]), "errores": leer(c["errores"])}
