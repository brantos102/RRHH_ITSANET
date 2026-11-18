"""El catálogo oficial de áreas y cargos.

Las fichas guardan el cargo y el área como texto (así estaban, y así siguen
funcionando informes, documentos y jefaturas). El catálogo es la lista
oficial de la que se elige, y sus operaciones mantienen las fichas al día:

  · renombrar un área o un cargo cambia el texto en todas las fichas que lo
    tienen;
  · unificar dos («BODEGA» y «Bodega Norte» → «Bodega») pasa a todas las
    personas al destino y deja un solo registro;
  · desactivar lo quita de las listas para elegir, sin tocar a quien ya lo
    tiene.

La colación de la base no distingue mayúsculas ni tildes, así que «bodega»
y «Bodega» son el mismo nombre para el catálogo.
"""
from __future__ import annotations

from typing import Any

from ..db import ejecutar, insertar, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio


def _nombre(texto: str | None) -> str:
    return " ".join((texto or "").split())


async def asegurar(cargo: str | None, area: str | None) -> None:
    """Que el cargo y el área de una ficha existan en el catálogo. Lo usa
    todo lo que escribe cargo o área (Talento Humano, aprobaciones, cargas
    masivas): lo que decide Talento Humano entra al catálogo."""
    area, cargo = _nombre(area), _nombre(cargo)
    area_id = None
    if area:
        await ejecutar("INSERT IGNORE INTO areas (nombre) VALUES (%s)", (area,))
        area_id = (await obtener_uno("SELECT id FROM areas WHERE nombre = %s", (area,)))["id"]
    if cargo:
        existe = await obtener_uno(
            "SELECT id FROM cargos WHERE nombre = %s AND area_id <=> %s", (cargo, area_id))
        if not existe:
            await ejecutar("INSERT INTO cargos (nombre, area_id) VALUES (%s, %s)", (cargo, area_id))


async def para_elegir() -> dict[str, list]:
    """Lo activo, para las listas de selección."""
    areas = await obtener_todos("SELECT id, nombre FROM areas WHERE activo ORDER BY nombre")
    cargos = await obtener_todos(
        """SELECT c.id, c.nombre, a.nombre AS area FROM cargos c
             LEFT JOIN areas a ON a.id = c.area_id
            WHERE c.activo AND (a.id IS NULL OR a.activo)
            ORDER BY a.nombre, c.nombre""")
    return {"areas": areas, "cargos": cargos}


async def resumen() -> dict[str, Any]:
    areas = await obtener_todos(
        """SELECT a.id, a.nombre, a.activo,
                  (SELECT COUNT(*) FROM users u WHERE u.activo AND TRIM(u.departamento) = a.nombre) AS personas,
                  (SELECT COUNT(*) FROM cargos c WHERE c.area_id = a.id) AS cargos
             FROM areas a ORDER BY a.nombre""")
    cargos = await obtener_todos(
        """SELECT c.id, c.nombre, c.activo, c.area_id, a.nombre AS area,
                  (SELECT COUNT(*) FROM users u WHERE u.activo AND TRIM(u.cargo) = c.nombre
                      AND (c.area_id IS NULL OR TRIM(u.departamento) = a.nombre)) AS personas
             FROM cargos c LEFT JOIN areas a ON a.id = c.area_id
            ORDER BY a.nombre, c.nombre""")
    # Lo que está en fichas y no en el catálogo (escrito a mano en la base).
    fuera = await obtener_todos(
        """SELECT 'area' AS tipo, TRIM(u.departamento) AS nombre, NULL AS area, COUNT(*) AS personas
             FROM users u
            WHERE u.activo AND NULLIF(TRIM(COALESCE(u.departamento, '')), '') IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM areas a WHERE a.nombre = TRIM(u.departamento))
            GROUP BY TRIM(u.departamento)
           UNION ALL
           SELECT 'cargo', TRIM(u.cargo), TRIM(u.departamento), COUNT(*)
             FROM users u
            WHERE u.activo AND NULLIF(TRIM(COALESCE(u.cargo, '')), '') IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cargos c LEFT JOIN areas a ON a.id = c.area_id
                               WHERE c.nombre = TRIM(u.cargo)
                                 AND (c.area_id IS NULL OR a.nombre = TRIM(u.departamento)))
            GROUP BY TRIM(u.cargo), TRIM(u.departamento)""")
    return {
        "areas": [{**a, "activo": bool(a["activo"]), "personas": int(a["personas"]),
                   "cargos": int(a["cargos"])} for a in areas],
        "cargos": [{**c, "activo": bool(c["activo"]), "personas": int(c["personas"])} for c in cargos],
        "fuera_de_catalogo": [{**f, "personas": int(f["personas"])} for f in fuera],
    }


# ------------------------------------------------------------------- áreas
async def crear_area(nombre: str) -> int:
    nombre = _nombre(nombre)
    if len(nombre) < 2:
        raise ReglaDeNegocio("Escriba el nombre del área.")
    if await obtener_uno("SELECT 1 AS x FROM areas WHERE nombre = %s", (nombre,)):
        raise ReglaDeNegocio(f"El área «{nombre}» ya existe.")
    return await insertar("INSERT INTO areas (nombre) VALUES (%s)", (nombre,))


async def cambiar_area(area_id: int, nombre: str | None, activo: bool | None) -> int:
    """Renombra (y cambia el texto en las fichas) o activa/desactiva.
    Devuelve cuántas fichas cambiaron."""
    actual = await obtener_uno("SELECT nombre FROM areas WHERE id = %s", (area_id,))
    if actual is None:
        raise ReglaDeNegocio("El área no existe.")
    fichas = 0
    async with transaccion():
        if nombre is not None:
            nombre = _nombre(nombre)
            if len(nombre) < 2:
                raise ReglaDeNegocio("Escriba el nombre del área.")
            otra = await obtener_uno("SELECT id FROM areas WHERE nombre = %s AND id <> %s", (nombre, area_id))
            if otra:
                raise ReglaDeNegocio(f"Ya existe «{nombre}». Para juntarlas use «Unificar».")
            fichas = await ejecutar("UPDATE users SET departamento = %s WHERE TRIM(departamento) = %s",
                                    (nombre, actual["nombre"]))
            await ejecutar("UPDATE areas SET nombre = %s WHERE id = %s", (nombre, area_id))
        if activo is not None:
            await ejecutar("UPDATE areas SET activo = %s WHERE id = %s", (activo, area_id))
    return fichas


async def unificar_areas(origen_id: int, destino_id: int) -> int:
    if origen_id == destino_id:
        raise ReglaDeNegocio("Elija un área distinta.")
    origen = await obtener_uno("SELECT id, nombre FROM areas WHERE id = %s", (origen_id,))
    destino = await obtener_uno("SELECT id, nombre FROM areas WHERE id = %s", (destino_id,))
    if not origen or not destino:
        raise ReglaDeNegocio("El área no existe.")
    async with transaccion():
        fichas = await ejecutar("UPDATE users SET departamento = %s WHERE TRIM(departamento) = %s",
                                (destino["nombre"], origen["nombre"]))
        # Los cargos del área de origen pasan al destino; si ya existe uno con
        # el mismo nombre allí, quedan como uno solo.
        for c in await obtener_todos("SELECT id, nombre FROM cargos WHERE area_id = %s", (origen_id,)):
            if await obtener_uno("SELECT 1 AS x FROM cargos WHERE nombre = %s AND area_id = %s",
                                 (c["nombre"], destino_id)):
                await ejecutar("DELETE FROM cargos WHERE id = %s", (c["id"],))
            else:
                await ejecutar("UPDATE cargos SET area_id = %s WHERE id = %s", (destino_id, c["id"]))
        await ejecutar("DELETE FROM areas WHERE id = %s", (origen_id,))
    return fichas


# ------------------------------------------------------------------ cargos
async def _area_nombre(area_id: int | None) -> str | None:
    if area_id is None:
        return None
    fila = await obtener_uno("SELECT nombre FROM areas WHERE id = %s", (area_id,))
    if fila is None:
        raise ReglaDeNegocio("El área no existe.")
    return fila["nombre"]


async def crear_cargo(nombre: str, area_id: int | None) -> int:
    nombre = _nombre(nombre)
    if len(nombre) < 2:
        raise ReglaDeNegocio("Escriba el nombre del cargo.")
    await _area_nombre(area_id)
    if await obtener_uno("SELECT 1 AS x FROM cargos WHERE nombre = %s AND area_id <=> %s", (nombre, area_id)):
        raise ReglaDeNegocio(f"El cargo «{nombre}» ya existe en esa área.")
    return await insertar("INSERT INTO cargos (nombre, area_id) VALUES (%s, %s)", (nombre, area_id))


async def _fichas_del_cargo(c: dict) -> tuple[str, tuple]:
    """Condición sobre users para las fichas que tienen ese cargo del catálogo."""
    area = await _area_nombre(c["area_id"])
    if area:
        return "TRIM(cargo) = %s AND TRIM(departamento) = %s", (c["nombre"], area)
    return "TRIM(cargo) = %s", (c["nombre"],)


async def cambiar_cargo(cargo_id: int, nombre: str | None, area_id: int | None, mover_area: bool,
                        activo: bool | None) -> int:
    c = await obtener_uno("SELECT id, nombre, area_id FROM cargos WHERE id = %s", (cargo_id,))
    if c is None:
        raise ReglaDeNegocio("El cargo no existe.")
    nuevo_nombre = _nombre(nombre) if nombre is not None else c["nombre"]
    nueva_area = area_id if mover_area else c["area_id"]
    if len(nuevo_nombre) < 2:
        raise ReglaDeNegocio("Escriba el nombre del cargo.")
    nombre_area = await _area_nombre(nueva_area)
    if (nuevo_nombre, nueva_area) != (c["nombre"], c["area_id"]) and await obtener_uno(
            "SELECT 1 AS x FROM cargos WHERE nombre = %s AND area_id <=> %s AND id <> %s",
            (nuevo_nombre, nueva_area, cargo_id)):
        raise ReglaDeNegocio(f"Ya existe «{nuevo_nombre}» en esa área. Para juntarlos use «Unificar».")
    fichas = 0
    async with transaccion():
        donde, params = await _fichas_del_cargo(c)
        sets, valores = ["cargo = %s"], [nuevo_nombre]
        if mover_area and nombre_area:
            sets.append("departamento = %s")
            valores.append(nombre_area)
        if (nuevo_nombre, nueva_area) != (c["nombre"], c["area_id"]):
            fichas = await ejecutar(f"UPDATE users SET {', '.join(sets)} WHERE {donde}", (*valores, *params))
            await ejecutar("UPDATE cargos SET nombre = %s, area_id = %s WHERE id = %s",
                           (nuevo_nombre, nueva_area, cargo_id))
        if activo is not None:
            await ejecutar("UPDATE cargos SET activo = %s WHERE id = %s", (activo, cargo_id))
    return fichas


async def unificar_cargos(origen_id: int, destino_id: int) -> int:
    if origen_id == destino_id:
        raise ReglaDeNegocio("Elija un cargo distinto.")
    origen = await obtener_uno("SELECT id, nombre, area_id FROM cargos WHERE id = %s", (origen_id,))
    destino = await obtener_uno("SELECT id, nombre, area_id FROM cargos WHERE id = %s", (destino_id,))
    if not origen or not destino:
        raise ReglaDeNegocio("El cargo no existe.")
    area_destino = await _area_nombre(destino["area_id"])
    async with transaccion():
        donde, params = await _fichas_del_cargo(origen)
        if area_destino:
            fichas = await ejecutar(f"UPDATE users SET cargo = %s, departamento = %s WHERE {donde}",
                                    (destino["nombre"], area_destino, *params))
        else:
            fichas = await ejecutar(f"UPDATE users SET cargo = %s WHERE {donde}", (destino["nombre"], *params))
        await ejecutar("DELETE FROM cargos WHERE id = %s", (origen_id,))
    return fichas
