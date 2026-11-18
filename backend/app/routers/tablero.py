"""El tablero de indicadores, por bloques que se encienden y se apagan.

Lo que aquí se muestra son AGREGADOS: cuántos, cuánto, en qué área. Ningún
nombre. «Cuántos están de vacaciones» es un número; quién está, es el
calendario del equipo, que tiene sus propios permisos. Un tablero que enseña
nombres a quien no le toca es una fuga de datos con buena presentación
(LOPDP, Art. 10: minimización).

Los números se calculan al pedirlos y no se guardan: un tablero con cifras
guardadas miente en cuanto alguien aprueba una solicitud, y lo peor es que
miente con aire de informe.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol

router = APIRouter(tags=["Tablero de indicadores"])

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class CambioBloque(BaseModel):
    """Lo que se puede cambiar de un indicador sin tocar código."""

    visible: bool | None = None
    orden: int | None = Field(None, ge=0, le=999)
    titulo: str | None = Field(None, min_length=3, max_length=60)
    # Cada indicador tiene los suyos: el umbral de días, cuántos meses de
    # historia, cuántas áreas listar.
    ajustes: dict | None = None


AJUSTES_PERMITIDOS = {
    "activos": {"meses": (1, 60)},
    "por_aprobar": {"dias_alerta": (1, 90)},
    "pasivo": {"umbral_persona": (1, 400)},
    "crecimiento": {"meses": (1, 60)},
    "por_area": {"cuantas": (1, 50)},
}


@router.get("/tablero")
async def tablero(usuario: RRHH) -> dict:
    """Los indicadores encendidos, con su número y su explicación."""
    bloques = await obtener_todos(
        """select b.clave, b.titulo, b.descripcion, b.pregunta, b.orden, b.ajustes,
                  b.actualizado_en, q.nombre as actualizado_por
             from public.tablero_bloques b
             left join public.users q on q.id = b.actualizado_por
            where b.visible
            order by b.orden""")
    calculados = {
        f["clave"]: f["datos"]
        for f in await obtener_todos("select clave, datos from public.tablero_indicadores()")
    }
    return {
        "bloques": [{**b, **(calculados.get(b["clave"]) or {})} for b in bloques],
        # La hora exacta del cálculo: un tablero sin ella se queda abierto en
        # una pantalla toda la tarde y se lee como si fuera de ahora.
        "calculado_en": (await obtener_uno("select now() as t"))["t"],
    }


@router.get("/admin/tablero")
async def listar_bloques(usuario: RRHH) -> list[dict]:
    """Todos, encendidos y apagados, para configurarlos."""
    return await obtener_todos(
        """select b.clave, b.titulo, b.descripcion, b.pregunta, b.visible, b.orden,
                  b.ajustes, b.actualizado_en, q.nombre as actualizado_por
             from public.tablero_bloques b
             left join public.users q on q.id = b.actualizado_por
            order by b.orden""")


@router.patch("/admin/tablero/{clave}")
async def cambiar_bloque(clave: str, cambio: CambioBloque,
                         request: Request, usuario: RRHH) -> dict:
    antes = await obtener_uno(
        "select titulo, visible, orden, ajustes from public.tablero_bloques where clave = %s",
        (clave,))
    if antes is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese indicador no existe."})

    ajustes = antes["ajustes"]
    if cambio.ajustes is not None:
        permitidos = AJUSTES_PERMITIDOS.get(clave, {})
        # Se validan aquí y no en la base porque el mensaje tiene que decir
        # qué ajuste y entre qué valores. Un 500 con un error de jsonb no le
        # sirve a quien está configurando una pantalla.
        for nombre, valor in cambio.ajustes.items():
            if nombre not in permitidos:
                raise HTTPException(status_code=422, detail={
                    "mensaje": f"«{nombre}» no es un ajuste de este indicador."})
            minimo, maximo = permitidos[nombre]
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail={
                    "mensaje": f"«{nombre}» tiene que ser un número."}) from None
            if not minimo <= numero <= maximo:
                raise HTTPException(status_code=422, detail={
                    "mensaje": f"«{nombre}» va entre {minimo} y {maximo}."})
        ajustes = {**ajustes, **cambio.ajustes}

    fila = await obtener_uno(
        """update public.tablero_bloques
              set visible = coalesce(%s, visible),
                  orden   = coalesce(%s, orden),
                  titulo  = coalesce(%s, titulo),
                  ajustes = %s,
                  actualizado_en = now(), actualizado_por = %s
            where clave = %s
          returning clave, titulo, visible""",
        (cambio.visible, cambio.orden, cambio.titulo, json.dumps(ajustes),
         str(usuario["id"]), clave))

    await registrar(request, "tablero_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="tablero_bloques", entidad_id=clave,
                    detalle={"antes": {"visible": antes["visible"], "orden": antes["orden"],
                                       "titulo": antes["titulo"], "ajustes": antes["ajustes"]},
                             "ahora": {"visible": fila["visible"], "titulo": fila["titulo"],
                                       "ajustes": ajustes}})
    return {"mensaje": f"«{fila['titulo']}» "
                       f"{'se muestra' if fila['visible'] else 'queda oculto'} en el tablero."}
