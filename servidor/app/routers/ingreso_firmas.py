"""Configuración del primer ingreso y de quién firma por Talento Humano.

Lo maneja Talento Humano y Administración desde el sistema:

  · Cómo se comprueba la identidad en el primer ingreso (correo o fecha de
    nacimiento) y qué se pide al entrar. Se muestra la cobertura de fechas de
    nacimiento para decidir cuándo pasar a verificar con ella.
  · Quién firma por Talento Humano en cada sede los documentos de
    vacaciones. La cabeza del departamento en la sede sale por defecto; quien
    imprime puede elegir a otro de la lista o dejarlo en blanco.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import booleanos, ejecutar, obtener_todos, obtener_uno, transaccion
from ..deps import exigir_rol
from ..errores import es_unicidad, traducir
from ..reglas import ingreso
from ..reglas import sedes as reglas_sedes

router = APIRouter(tags=["Primer ingreso y firmas"])
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]

ETIQUETAS = {
    "fecha_nacimiento": "Fecha de nacimiento",
    "fecha_ingreso": "Confirmar su fecha de ingreso (o pedir que la revisen)",
    "jefe": "Confirmar su jefe inmediato",
    "cargo": "Confirmar su cargo",
    "telefono": "Teléfono personal",
    "emergencia": "Contacto de emergencia",
}


class ConfigIngreso(BaseModel):
    modo: Literal["correo", "nacimiento"]
    campos: list[Literal["fecha_nacimiento", "fecha_ingreso", "jefe", "cargo",
                         "telefono", "emergencia"]]


class NuevoFirmante(BaseModel):
    region: str = Field(..., max_length=20)
    user_id: str = Field(..., max_length=40)
    cargo_firma: str | None = Field(None, max_length=120)
    principal: bool = False


class CambioFirmante(BaseModel):
    cargo_firma: str | None = Field(None, max_length=120)
    principal: bool | None = None


# ------------------------------------------------------------ primer ingreso
@router.get("/admin/ingreso")
async def ver_ingreso(usuario: RRHH) -> dict:
    return {
        "modo": await ingreso.modo_alta(),
        "campos": await ingreso.campos_ficha_inicial(),
        "disponibles": [{"campo": c, "etiqueta": ETIQUETAS[c]} for c in ingreso.CAMPOS],
        "cobertura": await ingreso.cobertura(),
    }


@router.patch("/admin/ingreso")
async def cambiar_ingreso(datos: ConfigIngreso, request: Request, usuario: RRHH) -> dict:
    antes = {"modo": await ingreso.modo_alta(), "campos": await ingreso.campos_ficha_inicial()}
    campos = [c for c in ingreso.CAMPOS if c in datos.campos]     # orden fijo, sin repetidos
    await ejecutar("UPDATE app_config SET valor = %s WHERE clave = 'alta_verificacion'",
                   (datos.modo,))
    await ejecutar("UPDATE app_config SET valor = %s WHERE clave = 'ficha_inicial_campos'",
                   (",".join(campos),))
    await registrar(request, "ingreso_configurado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="app_config",
                    detalle={"antes": antes, "ahora": {"modo": datos.modo, "campos": campos}})
    return {"mensaje": "Configuración del primer ingreso guardada."
                       + (" Desde ahora, quien no tiene correo debe comprobar su fecha de "
                          "nacimiento." if datos.modo == "nacimiento" else "")}


# ----------------------------------------------------------------- firmantes
SQL_FIRMANTES = """
    SELECT f.id, f.region, f.user_id, f.cargo_firma, f.principal,
           u.nombre, u.cargo, u.cedula, u.activo
      FROM firmantes_rrhh f JOIN users u ON u.id = f.user_id
"""


def _firmante(f: dict, SEDES: dict) -> dict:
    return {**f, "id": int(f["id"]), "user_id": str(f["user_id"]),
            "sede": SEDES.get(f["region"], f["region"]),
            "firma_como": f["cargo_firma"] or f["cargo"] or "Talento Humano"}


async def firmantes_de(region: str | None) -> list[dict]:
    """Los de esa sede, el principal primero. Lo usan también los documentos."""
    filas = await obtener_todos(
        SQL_FIRMANTES + " WHERE f.region = %s AND u.activo ORDER BY f.principal DESC, u.nombre",
        (region or "sierra",))
    SEDES = await reglas_sedes.nombres()
    return [_firmante(f, SEDES) for f in booleanos(filas, "principal", "activo")]


@router.get("/admin/firmantes")
async def listar_firmantes(usuario: RRHH) -> dict:
    filas = booleanos(await obtener_todos(SQL_FIRMANTES + " ORDER BY f.region, f.principal DESC, u.nombre"),
                      "principal", "activo")
    candidatos = await obtener_todos(
        """SELECT id, nombre, cargo, COALESCE(region, 'sierra') AS region FROM users
            WHERE activo AND rol IN ('rrhh', 'admin') ORDER BY nombre""")
    SEDES = await reglas_sedes.nombres()
    return {"firmantes": [_firmante(f, SEDES) for f in filas],
            "candidatos": [{**c, "id": str(c["id"])} for c in candidatos],
            "sedes": [{"region": r, "sede": s} for r, s in SEDES.items()]}


@router.get("/papeles/firmantes")
async def firmantes_para_imprimir(usuario: RRHH, region: str = "sierra") -> list[dict]:
    """Para elegir quién firma por Talento Humano al imprimir."""
    return await firmantes_de(region)


async def _quitar_principal(region: str, salvo: int | None = None) -> None:
    await ejecutar("UPDATE firmantes_rrhh SET principal = FALSE WHERE region = %s AND principal"
                   + (" AND id <> %s" if salvo else ""),
                   (region, salvo) if salvo else (region,))


@router.post("/admin/firmantes", status_code=201)
async def agregar_firmante(datos: NuevoFirmante, request: Request, usuario: RRHH) -> dict:
    try:
        await reglas_sedes.validar(datos.region)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    SEDES = await reglas_sedes.nombres()
    persona = await obtener_uno(
        "SELECT nombre FROM users WHERE id = %s AND activo AND rol IN ('rrhh', 'admin')",
        (datos.user_id,))
    if persona is None:
        raise HTTPException(status_code=422, detail={
            "mensaje": "Solo puede firmar por Talento Humano alguien que integre el "
                       "departamento (rol Talento Humano o Administración)."})
    try:
        async with transaccion():
            if datos.principal:
                await _quitar_principal(datos.region)
            await ejecutar(
                """INSERT INTO firmantes_rrhh (region, user_id, cargo_firma, principal, creado_por)
                   VALUES (%s, %s, %s, %s, %s)""",
                (datos.region, datos.user_id, (datos.cargo_firma or "").strip() or None,
                 datos.principal, str(usuario["id"])))
    except Exception as exc:  # noqa: BLE001
        if es_unicidad(exc):
            raise HTTPException(status_code=409, detail={
                "mensaje": f"{persona['nombre']} ya firma en esa sede."}) from exc
        raise traducir(exc) from exc
    await registrar(request, "firmante_agregado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="firmantes_rrhh",
                    detalle={"region": datos.region, "firmante": persona["nombre"],
                             "principal": datos.principal})
    return {"mensaje": f"{persona['nombre']} firmará por Talento Humano en "
                       f"{SEDES[datos.region]}" + (" como cabeza del departamento." if datos.principal else ".")}


@router.patch("/admin/firmantes/{firmante_id}")
async def cambiar_firmante(firmante_id: int, datos: CambioFirmante, request: Request,
                           usuario: RRHH) -> dict:
    f = await obtener_uno("SELECT region FROM firmantes_rrhh WHERE id = %s", (firmante_id,))
    if f is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese firmante no existe."})
    async with transaccion():
        if datos.principal:
            await _quitar_principal(f["region"], salvo=firmante_id)
        if datos.principal is not None:
            await ejecutar("UPDATE firmantes_rrhh SET principal = %s WHERE id = %s",
                           (datos.principal, firmante_id))
        if datos.cargo_firma is not None:
            await ejecutar("UPDATE firmantes_rrhh SET cargo_firma = %s WHERE id = %s",
                           (datos.cargo_firma.strip() or None, firmante_id))
    await registrar(request, "firmante_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="firmantes_rrhh",
                    entidad_id=str(firmante_id), detalle=datos.model_dump(exclude_none=True))
    return {"mensaje": "Firmante actualizado."}


@router.delete("/admin/firmantes/{firmante_id}")
async def quitar_firmante(firmante_id: int, request: Request, usuario: RRHH) -> dict:
    await ejecutar("DELETE FROM firmantes_rrhh WHERE id = %s", (firmante_id,))
    await registrar(request, "firmante_quitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="firmantes_rrhh",
                    entidad_id=str(firmante_id))
    return {"mensaje": "Ya no firma por Talento Humano en esa sede."}
