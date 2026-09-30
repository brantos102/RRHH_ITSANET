"""Qué se muestra en la pantalla principal, y quién lo decide.

El panel del colaborador se fue llenando de bloques y todos se mostraban
siempre a todo el mundo. No todas las empresas quieren lo mismo en la primera
pantalla: hay quien no usa firma electrónica, quien prefiere que el calendario
del equipo lo vea solo jefatura, y quien necesita poner un aviso arriba
durante una semana.

Hasta ahora eso se cambiaba editando el HTML. Un sistema oficial no se
administra tocando archivos: se administra desde una pantalla, deja constancia
de quién cambió qué y se puede deshacer.

Dos cosas que no hace:

Ocultar no borra. Es una decisión de presentación; el dato se sigue
calculando y se sigue consultando por su propia pantalla. Apagar «Ausencias
del equipo» no cancela ninguna ausencia.

No manda la lista entera al navegador. El filtrado por rol se hace en la base
y viaja ya filtrado: mandar todo con un «no mires estos» es esconder algo
donde cualquiera lo encuentra abriendo las herramientas del navegador.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir

router = APIRouter(prefix="/panel", tags=["Pantalla principal"])

ADMIN = Annotated[dict, Depends(exigir_rol("admin"))]
QUIEN_SEA = Annotated[dict, Depends(usuario_actual)]

Rol = Literal["admin", "rrhh", "jefe", "empleado", "guardia"]


class CambioBloque(BaseModel):
    """Lo que el administrador puede cambiar de un bloque.

    Todo opcional: la pantalla manda solo lo que tocó, y lo que no manda se
    queda como estaba. Así dos administradores trabajando a la vez no se
    pisan lo que el otro acaba de cambiar.
    """

    visible: bool | None = None
    orden: int | None = Field(None, ge=0, le=999)
    roles: list[Rol] | None = None
    cuerpo: str | None = Field(None, max_length=600)


@router.get("/bloques", summary="Los bloques que esta persona debe ver")
async def mis_bloques(usuario: QUIEN_SEA) -> dict:
    """Ya filtrado por rol, y sin el aviso si está vacío."""
    filas = await obtener_todos("select * from public.panel_de(%s)", (usuario["id"],))
    return {"bloques": [dict(f) for f in filas]}


@router.get("/configuracion", summary="Todos los bloques, para administrarlos")
async def configuracion(_: ADMIN) -> dict:
    filas = await obtener_todos("select * from public.v_panel_configuracion")
    return {"bloques": [dict(f) for f in filas]}


@router.patch("/configuracion/{clave}", summary="Cambiar un bloque")
async def cambiar(clave: str, cambio: CambioBloque, request: Request,
                  admin: ADMIN) -> dict:
    try:
        fila = await obtener_uno(
            """select * from public.panel_configurar(
                   %s, %s, %s, %s::smallint, %s::public.user_role[], %s)""",
            (clave, admin["id"], cambio.visible, cambio.orden,
             cambio.roles, cambio.cuerpo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "panel.configurar", user_id=admin["id"],
                    cedula=admin["cedula"], entidad="panel_bloques",
                    entidad_id=clave,
                    detalle=cambio.model_dump(exclude_none=True))
    return dict(fila)


class Orden(BaseModel):
    claves: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/configuracion/orden", summary="Reordenar la pantalla")
async def reordenar(orden: Orden, request: Request, admin: ADMIN) -> dict:
    """De diez en diez y no de uno en uno.

    Deja hueco entre bloques para que intercalar uno nuevo en una versión
    futura no obligue a renumerar toda la pantalla.
    """
    for posicion, clave in enumerate(orden.claves, start=1):
        try:
            await obtener_uno(
                "select * from public.panel_configurar(%s, %s, null, %s::smallint)",
                (clave, admin["id"], posicion * 10),
            )
        except Exception as exc:  # noqa: BLE001
            raise traducir(exc) from exc

    await registrar(request, "panel.reordenar", user_id=admin["id"],
                    cedula=admin["cedula"], entidad="panel_bloques",
                    detalle={"orden": orden.claves})
    filas = await obtener_todos("select * from public.v_panel_configuracion")
    return {"bloques": [dict(f) for f in filas]}
