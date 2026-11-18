"""Las sedes de Talento Humano, sus regiones del Ecuador y sus ciudades.

En la base, cada sede es una fila de `regiones` (por historia: empezó siendo
«Sierra» y «Costa»). La persona pertenece a la sede de su ciudad: un
disparador de la base la deduce al cambiar la ciudad, con la tabla
`ciudades_region`. Aquí se administra todo eso desde el sistema:

  · crear una sede nueva (Cuenca, Manta…) y decir qué regiones naturales del
    Ecuador atiende;
  · registrar ciudades con su provincia y su región natural, y pasarlas de
    una sede a otra. Al pasarlas, quienes viven ahí cambian de sede y sus
    trámites en curso los siguen;
  · ver a quién no se le reconoce la ciudad (y por eso quedó, por defecto,
    en la sede de Quito).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..db import ejecutar, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio

REGIONES_NATURALES = {"costa": "Costa", "sierra": "Sierra", "amazonia": "Amazonía",
                      "insular": "Galápagos"}
_CODIGO = re.compile(r"^[a-z][a-z0-9_]{1,19}$")


def _plano(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()


def codigo_para(sede: str) -> str:
    """«Santo Domingo» -> «santo_domingo». Máximo 20 caracteres."""
    base = re.sub(r"[^a-z0-9]+", "_", _plano(sede).lower()).strip("_")[:20].strip("_")
    if not base or not base[0].isalpha():
        base = f"sede_{base}"[:20]
    return base


def ciudad_normal(ciudad: str) -> str:
    """Las ciudades se guardan en mayúsculas, sin espacios dobles."""
    return " ".join((ciudad or "").split()).upper()


def _naturales(lista: list[str] | None) -> str | None:
    valores = [v for v in (lista or []) if v in REGIONES_NATURALES]
    return ",".join(dict.fromkeys(valores)) or None


async def nombres() -> dict[str, str]:
    """{código: ciudad de la sede}, de todas (también las inactivas, para
    leer lo histórico)."""
    return {f["codigo"]: f["sede"] for f in await obtener_todos(
        "SELECT codigo, sede FROM regiones ORDER BY orden, codigo")}


async def validar(codigo: str | None, *, permitir_nulo: bool = False) -> str | None:
    """El código de una sede activa, o error claro."""
    if codigo is None and permitir_nulo:
        return None
    if not codigo or not _CODIGO.match(codigo):
        raise ReglaDeNegocio("La sede indicada no existe.")
    fila = await obtener_uno("SELECT codigo FROM regiones WHERE codigo = %s AND activo", (codigo,))
    if fila is None:
        raise ReglaDeNegocio("La sede indicada no existe o está desactivada.")
    return fila["codigo"]


async def catalogo() -> list[dict[str, Any]]:
    """Las sedes activas, para los selectores."""
    filas = await obtener_todos(
        """SELECT codigo, nombre, sede, regiones_naturales FROM regiones
            WHERE activo ORDER BY orden, codigo""")
    return [{**f, "regiones_naturales": (f["regiones_naturales"] or "").split(",")
             if f["regiones_naturales"] else []} for f in filas]


async def resumen() -> dict[str, Any]:
    """Todo lo que muestra la pantalla «Sedes y regiones»."""
    sedes = await obtener_todos(
        """SELECT g.codigo, g.nombre, g.sede, g.descripcion, g.regiones_naturales, g.activo, g.orden,
                  cfg_texto(CONCAT('rrhh_correo_', g.codigo)) AS correo,
                  (SELECT COUNT(*) FROM users u WHERE u.activo AND u.region = g.codigo) AS personas,
                  (SELECT COUNT(*) FROM ciudades_region c WHERE c.region = g.codigo) AS ciudades,
                  (SELECT COUNT(*) FROM v_rrhh_por_region t WHERE t.region = g.codigo) AS talento_humano,
                  (SELECT COUNT(*) FROM firmantes_rrhh f WHERE f.region = g.codigo) AS firmantes
             FROM regiones g ORDER BY g.orden, g.codigo""")
    ciudades = await obtener_todos(
        """SELECT c.ciudad, c.provincia, c.region_natural, c.region,
                  (SELECT COUNT(*) FROM users u WHERE u.activo AND TRIM(u.ciudad) = c.ciudad) AS personas
             FROM ciudades_region c ORDER BY c.ciudad""")
    # Ciudad escrita que no está en la tabla: la persona quedó en la sede
    # por defecto sin que nadie lo decidiera.
    sin_ciudad = await obtener_todos(
        """SELECT COALESCE(NULLIF(TRIM(u.ciudad), ''), '(sin ciudad)') AS ciudad,
                  COUNT(*) AS personas, MIN(COALESCE(u.region, 'sierra')) AS region
             FROM users u
            WHERE u.activo AND NOT EXISTS (
                  SELECT 1 FROM ciudades_region c WHERE c.ciudad = TRIM(COALESCE(u.ciudad, '')))
            GROUP BY 1 ORDER BY 2 DESC LIMIT 200""")
    return {
        "sedes": [{**s, "activo": bool(s["activo"]), "personas": int(s["personas"]),
                   "ciudades": int(s["ciudades"]), "talento_humano": int(s["talento_humano"]),
                   "firmantes": int(s["firmantes"]),
                   "regiones_naturales": (s["regiones_naturales"] or "").split(",")
                   if s["regiones_naturales"] else []} for s in sedes],
        "ciudades": [{**c, "personas": int(c["personas"])} for c in ciudades],
        "sin_ciudad": [{**c, "personas": int(c["personas"])} for c in sin_ciudad],
        "regiones_naturales": REGIONES_NATURALES,
    }


async def crear_sede(sede: str, nombre: str, descripcion: str | None,
                     naturales: list[str] | None, correo: str | None) -> str:
    sede = " ".join((sede or "").split()).title()
    if len(sede) < 3:
        raise ReglaDeNegocio("Escriba la ciudad donde está la sede.")
    codigo = codigo_para(sede)
    if await obtener_uno("SELECT 1 AS x FROM regiones WHERE codigo = %s", (codigo,)):
        raise ReglaDeNegocio(f"Ya existe una sede con el código «{codigo}».")
    async with transaccion():
        orden = (await obtener_uno("SELECT COALESCE(MAX(orden), 0) + 10 AS o FROM regiones"))["o"]
        await ejecutar(
            """INSERT INTO regiones (codigo, nombre, sede, regiones_naturales, descripcion, activo, orden)
               VALUES (%s, %s, %s, %s, %s, TRUE, %s)""",
            (codigo, (nombre or "").strip() or f"Sede {sede}", sede, _naturales(naturales),
             (descripcion or "").strip() or None, orden))
        await ejecutar(
            """INSERT INTO app_config (clave, valor, descripcion) VALUES (%s, %s, %s)
               AS nuevo ON DUPLICATE KEY UPDATE valor = nuevo.valor""",
            (f"rrhh_correo_{codigo}", (correo or "").strip(),
             f"Correo del departamento de Talento Humano en la sede {sede}."))
        # La ciudad de la sede queda registrada y atendida por ella.
        ciudad = ciudad_normal(sede)
        if not await obtener_uno("SELECT 1 AS x FROM ciudades_region WHERE ciudad = %s", (ciudad,)):
            await ejecutar("INSERT INTO ciudades_region (ciudad, region) VALUES (%s, %s)",
                           (ciudad, codigo))
    return codigo


async def cambiar_sede(codigo: str, cambios: dict[str, Any]) -> None:
    actual = await obtener_uno("SELECT codigo FROM regiones WHERE codigo = %s", (codigo,))
    if actual is None:
        raise ReglaDeNegocio("La sede no existe.")
    if cambios.get("activo") is False:
        uso = await obtener_uno(
            """SELECT (SELECT COUNT(*) FROM users WHERE activo AND region = %s) AS personas,
                      (SELECT COUNT(*) FROM ciudades_region WHERE region = %s) AS ciudades""",
            (codigo, codigo))
        if uso["personas"] or uso["ciudades"]:
            raise ReglaDeNegocio(
                f"No se puede desactivar: atiende {uso['ciudades']} ciudad(es) y "
                f"{uso['personas']} persona(s). Pase antes sus ciudades a otra sede.")
    sets, valores = [], []
    for campo in ("nombre", "sede", "descripcion"):
        if campo in cambios and cambios[campo] is not None:
            sets.append(f"{campo} = %s")
            valores.append(" ".join(str(cambios[campo]).split()) or None)
    if "regiones_naturales" in cambios and cambios["regiones_naturales"] is not None:
        sets.append("regiones_naturales = %s")
        valores.append(_naturales(cambios["regiones_naturales"]))
    if cambios.get("activo") is not None:
        sets.append("activo = %s")
        valores.append(bool(cambios["activo"]))
    async with transaccion():
        if sets:
            await ejecutar(f"UPDATE regiones SET {', '.join(sets)} WHERE codigo = %s",
                           (*valores, codigo))
        if cambios.get("correo") is not None:
            await ejecutar(
                """INSERT INTO app_config (clave, valor, descripcion) VALUES (%s, %s, %s)
                   AS nuevo ON DUPLICATE KEY UPDATE valor = nuevo.valor""",
                (f"rrhh_correo_{codigo}", cambios["correo"].strip(),
                 "Correo del departamento de Talento Humano de la sede."))


async def guardar_ciudad(ciudad: str, region: str, provincia: str | None,
                         region_natural: str | None) -> dict[str, int]:
    """Registra la ciudad o la pasa de sede. Quienes viven ahí cambian de
    sede con ella, y sus trámites en curso los siguen."""
    from .personal import mover_pendientes_de_sede
    ciudad = ciudad_normal(ciudad)
    if len(ciudad) < 3:
        raise ReglaDeNegocio("Escriba el nombre de la ciudad.")
    await validar(region)
    if region_natural is not None and region_natural not in REGIONES_NATURALES:
        raise ReglaDeNegocio("Región natural no válida.")
    async with transaccion():
        await ejecutar(
            """INSERT INTO ciudades_region (ciudad, provincia, region_natural, region)
               VALUES (%s, %s, %s, %s)
               AS nuevo ON DUPLICATE KEY UPDATE provincia = nuevo.provincia,
                  region_natural = nuevo.region_natural, region = nuevo.region""",
            (ciudad, (provincia or "").strip() or None, region_natural, region))
        afectados = await obtener_todos(
            """SELECT id FROM users WHERE activo AND TRIM(ciudad) = %s
                  AND NOT (COALESCE(region, '') <=> %s)""", (ciudad, region))
        if afectados:
            await ejecutar("UPDATE users SET region = %s WHERE TRIM(ciudad) = %s", (region, ciudad))
        movidas = 0
        for a in afectados:
            movidas += await mover_pendientes_de_sede(a["id"])
    return {"personas": len(afectados), "tramites": movidas}


async def quitar_ciudad(ciudad: str) -> None:
    ciudad = ciudad_normal(ciudad)
    uso = await obtener_uno("SELECT COUNT(*) AS n FROM users WHERE activo AND TRIM(ciudad) = %s",
                            (ciudad,))
    if uso["n"]:
        raise ReglaDeNegocio(f"{uso['n']} persona(s) activas tienen esa ciudad: no se puede quitar.")
    n = await ejecutar("DELETE FROM ciudades_region WHERE ciudad = %s", (ciudad,))
    if not n:
        raise ReglaDeNegocio("Esa ciudad no está registrada.")
