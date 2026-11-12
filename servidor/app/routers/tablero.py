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
from ..db import ejecutar, obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..errores import traducir
from ..reglas import tablero as reglas_tablero
from ..reglas.tablero import tablero_indicadores

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
    "cuota_discapacidad": {"porcentaje": (1, 20)},
}


@router.get("/tablero")
async def tablero(usuario: RRHH) -> dict:
    """Los indicadores encendidos, con su número y su explicación."""
    bloques = await obtener_todos(
        """select b.clave, b.titulo, b.descripcion, b.pregunta, b.orden, b.ajustes,
                  b.actualizado_en, q.nombre as actualizado_por
             from tablero_bloques b
             left join users q on q.id = b.actualizado_por
            where b.visible
            order by b.orden""")
    calculados = {
        f["clave"]: f["datos"]
        for f in await tablero_indicadores()
    }
    return {
        "bloques": [{**b, **(calculados.get(b["clave"]) or {})} for b in bloques],
        # La hora exacta del cálculo: un tablero sin ella se queda abierto en
        # una pantalla toda la tarde y se lee como si fuera de ahora.
        "calculado_en": (await obtener_uno("select now(6) as t"))["t"],
    }


@router.get("/admin/tablero")
async def listar_bloques(usuario: RRHH) -> list[dict]:
    """Todos, encendidos y apagados, para configurarlos."""
    return await obtener_todos(
        """select b.clave, b.titulo, b.descripcion, b.pregunta, b.visible, b.orden,
                  b.ajustes, b.actualizado_en, q.nombre as actualizado_por
             from tablero_bloques b
             left join users q on q.id = b.actualizado_por
            order by b.orden""")


@router.patch("/admin/tablero/{clave}")
async def cambiar_bloque(clave: str, cambio: CambioBloque,
                         request: Request, usuario: RRHH) -> dict:
    antes = await obtener_uno(
        "select titulo, visible, orden, ajustes from tablero_bloques where clave = %s",
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

    await ejecutar(
        """update tablero_bloques
              set visible = coalesce(%s, visible),
                  orden   = coalesce(%s, orden),
                  titulo  = coalesce(%s, titulo),
                  ajustes = %s,
                  actualizado_en = now(6), actualizado_por = %s
            where clave = %s""",
        (cambio.visible, cambio.orden, cambio.titulo, json.dumps(ajustes),
         str(usuario["id"]), clave))
    fila = await obtener_uno(
        "select clave, titulo, visible from tablero_bloques where clave = %s", (clave,))

    await registrar(request, "tablero_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="tablero_bloques", entidad_id=clave,
                    detalle={"antes": {"visible": antes["visible"], "orden": antes["orden"],
                                       "titulo": antes["titulo"], "ajustes": antes["ajustes"]},
                             "ahora": {"visible": fila["visible"], "titulo": fila["titulo"],
                                       "ajustes": ajustes}})
    return {"mensaje": f"«{fila['titulo']}» "
                       f"{'se muestra' if fila['visible'] else 'queda oculto'} en el tablero."}


# ------------------------------------------------------------------ explorador
class Filtros(BaseModel):
    sede: str | None = Field(None, max_length=20)
    area: str | None = Field(None, max_length=120)
    desde: str | None = Field(None, max_length=10)
    hasta: str | None = Field(None, max_length=10)
    tipo: Literal["vacacion", "permiso"] | None = None


class Vista(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)
    medida: str = Field(..., max_length=30)
    dimension: str = Field(..., max_length=30)
    grafico: Literal["barras", "linea", "tabla", "cifra"] = "barras"
    filtros: Filtros = Filtros()
    ancho: Literal[1, 2] = 1
    compartida: bool = False


class CambioVista(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=120)
    medida: str | None = Field(None, max_length=30)
    dimension: str | None = Field(None, max_length=30)
    grafico: Literal["barras", "linea", "tabla", "cifra"] | None = None
    filtros: Filtros | None = None
    ancho: Literal[1, 2] | None = None
    compartida: bool | None = None
    orden: int | None = Field(None, ge=0, le=9999)


@router.get("/tablero/explorador")
async def catalogo_explorador(usuario: RRHH) -> dict:
    """Qué se puede medir, por qué se puede agrupar y con qué filtrar."""
    areas = await obtener_todos(
        """select distinct departamento as area from users
            where activo and departamento is not null and trim(departamento) <> ''
            order by 1""")
    sedes = await obtener_todos("select codigo, sede from regiones where activo order by orden, codigo")
    return {**reglas_tablero.catalogo_explorador(),
            "areas": [a["area"] for a in areas], "sedes": sedes}


@router.get("/tablero/explorar")
async def explorar(usuario: RRHH, medida: str, dimension: str, sede: str | None = None,
                   area: str | None = None, desde: str | None = None, hasta: str | None = None,
                   tipo: str | None = None) -> dict:
    try:
        return await reglas_tablero.explorar(
            medida, dimension, {"sede": sede, "area": area, "desde": desde, "hasta": hasta, "tipo": tipo})
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc


def _validar_vista(medida: str, dimension: str) -> None:
    if medida not in reglas_tablero.MEDIDAS or dimension not in reglas_tablero.DIMENSIONES:
        raise HTTPException(status_code=422, detail={"mensaje": "Medida o dimensión desconocida."})


@router.get("/tablero/vistas")
async def mis_vistas(usuario: RRHH) -> list[dict]:
    """Las propias y las que el resto de Talento Humano compartió."""
    filas = await obtener_todos(
        """select v.id, v.nombre, v.medida, v.dimension, v.grafico, v.filtros, v.orden, v.ancho,
                  v.compartida, v.creado_por = %s as propia, q.nombre as de
             from tablero_vistas v join users q on q.id = v.creado_por
            where v.creado_por = %s or v.compartida
            order by (v.creado_por = %s) desc, v.orden, v.id""",
        (str(usuario["id"]), str(usuario["id"]), str(usuario["id"])))
    return [{**f, "id": int(f["id"]), "propia": bool(f["propia"]), "compartida": bool(f["compartida"]),
             "filtros": json.loads(f["filtros"]) if isinstance(f["filtros"], str) else f["filtros"]}
            for f in filas]


@router.post("/tablero/vistas", status_code=201)
async def guardar_vista(datos: Vista, request: Request, usuario: RRHH) -> dict:
    _validar_vista(datos.medida, datos.dimension)
    from ..db import insertar
    siguiente = (await obtener_uno(
        "select coalesce(max(orden), 0) + 10 as o from tablero_vistas where creado_por = %s",
        (str(usuario["id"]),)))["o"]
    nuevo = await insertar(
        """insert into tablero_vistas (nombre, medida, dimension, grafico, filtros, orden, ancho,
                                       compartida, creado_por)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (datos.nombre.strip(), datos.medida, datos.dimension, datos.grafico,
         json.dumps(datos.filtros.model_dump(exclude_none=True)), siguiente, datos.ancho,
         datos.compartida, str(usuario["id"])))
    await registrar(request, "tablero_vista_creada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="tablero_vistas", entidad_id=str(nuevo),
                    detalle=datos.model_dump(mode="json"))
    return {"id": int(nuevo), "mensaje": "Gráfico agregado a su tablero."}


async def _propia(vista_id: int, usuario: dict) -> dict:
    fila = await obtener_uno("select id, creado_por from tablero_vistas where id = %s", (vista_id,))
    if fila is None or (str(fila["creado_por"]) != str(usuario["id"]) and usuario["rol"] != "admin"):
        raise HTTPException(status_code=404, detail={
            "mensaje": "Ese gráfico no existe o es de otra persona (puede copiarlo al suyo)."})
    return fila


@router.patch("/tablero/vistas/{vista_id}")
async def cambiar_vista(vista_id: int, datos: CambioVista, usuario: RRHH) -> dict:
    await _propia(vista_id, usuario)
    cambios = datos.model_dump(exclude_none=True)
    if not cambios:
        raise HTTPException(status_code=422, detail={"mensaje": "No indicó ningún cambio."})
    actual = await obtener_uno("select medida, dimension from tablero_vistas where id = %s", (vista_id,))
    _validar_vista(cambios.get("medida", actual["medida"]), cambios.get("dimension", actual["dimension"]))
    if "filtros" in cambios:
        cambios["filtros"] = json.dumps(datos.filtros.model_dump(exclude_none=True))
    asignaciones = ", ".join(f"{k} = %({k})s" for k in cambios)
    await ejecutar(f"update tablero_vistas set {asignaciones} where id = %(id)s", {**cambios, "id": vista_id})
    return {"mensaje": "Gráfico actualizado."}


@router.delete("/tablero/vistas/{vista_id}")
async def quitar_vista(vista_id: int, usuario: RRHH) -> dict:
    await _propia(vista_id, usuario)
    await ejecutar("delete from tablero_vistas where id = %s", (vista_id,))
    return {"mensaje": "Gráfico quitado del tablero."}
