"""Los indicadores del tablero, calculados al pedirlos.

Reemplaza a tablero_indicadores. Solo agregados: ningún nombre (LOPDP,
Art. 10). Solo se calcula lo que está encendido: apagar un bloque lo quita
de la pantalla y deja de costarlo.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ..db import lista, obtener_todos, obtener_uno, para_json


def _entero(ajustes: dict, clave: str, omision: int) -> int:
    try:
        return int(ajustes.get(clave, omision))
    except (TypeError, ValueError):
        return omision


async def _ausentes_hoy(_: dict) -> dict:
    f = await obtener_uno(
        """SELECT COUNT(*) AS cifra,
                  COALESCE(SUM(r.tipo = 'vacacion'), 0) AS vacaciones,
                  COALESCE(SUM(r.tipo <> 'vacacion'), 0) AS permisos,
                  (SELECT COUNT(*) FROM users WHERE activo) AS de
             FROM requests r
            WHERE r.estado = 'aprobado'
              AND CURRENT_DATE() BETWEEN r.fecha_inicio AND r.fecha_fin""")
    return {"cifra": f["cifra"],
            "detalle": {"vacaciones": f["vacaciones"], "permisos": f["permisos"], "de": f["de"]}}


async def _activos(ajustes: dict) -> dict:
    meses = _entero(ajustes, "meses", 12)
    f = await obtener_uno(
        """SELECT COALESCE(SUM(u.activo), 0) AS cifra,
                  COALESCE(SUM(u.fecha_ingreso >= d.desde), 0) AS altas,
                  COALESCE(SUM(u.fecha_salida IS NOT NULL AND u.fecha_salida >= d.desde), 0) AS bajas
             FROM users u
             CROSS JOIN (SELECT CURRENT_DATE() - INTERVAL %s MONTH AS desde) d""", (meses,))
    return {"cifra": f["cifra"], "detalle": {"altas": f["altas"], "bajas": f["bajas"], "meses": meses}}


async def _por_aprobar(ajustes: dict) -> dict:
    dias = _entero(ajustes, "dias_alerta", 3)
    f = await obtener_uno(
        """SELECT COUNT(*) AS cifra,
                  COALESCE(SUM(r.estado = 'pendiente_jefe' AND r.jefe_id IS NOT NULL), 0) AS con_jefe,
                  COALESCE(SUM(r.estado = 'pendiente_jefe' AND r.jefe_id IS NULL), 0) AS sin_jefe,
                  COALESCE(SUM(r.estado = 'pendiente_rrhh'), 0) AS en_rrhh,
                  COALESCE(SUM(r.created_at < NOW(6) - INTERVAL %s DAY), 0) AS atrasadas,
                  MAX(DATEDIFF(CURRENT_DATE(), DATE(r.created_at))) AS la_mas_vieja
             FROM requests r
            WHERE r.estado IN ('pendiente_jefe', 'pendiente_rrhh')""", (dias,))
    return {"cifra": f["cifra"],
            "detalle": {"con_jefe": f["con_jefe"], "sin_jefe": f["sin_jefe"], "en_rrhh": f["en_rrhh"],
                        "atrasadas": f["atrasadas"], "dias_alerta": dias,
                        "la_mas_vieja": f["la_mas_vieja"]}}


async def _sin_jefe(_: dict) -> dict:
    f = await obtener_uno(
        """SELECT COUNT(*) AS cifra,
                  (SELECT COUNT(*) FROM users WHERE activo) AS de,
                  (SELECT COUNT(*) FROM requests r JOIN users u2 ON u2.id = r.user_id
                    WHERE u2.jefe_id IS NULL AND u2.activo
                      AND r.estado IN ('pendiente_jefe', 'pendiente_rrhh')) AS abiertas
             FROM users u WHERE u.activo AND u.jefe_id IS NULL""")
    return {"cifra": f["cifra"], "detalle": {"de": f["de"], "con_solicitudes_abiertas": f["abiertas"]}}


async def _pasivo(ajustes: dict) -> dict:
    try:
        umbral = float(ajustes.get("umbral_persona", 30))
    except (TypeError, ValueError):
        umbral = 30.0
    f = await obtener_uno(
        """SELECT ROUND(COALESCE(SUM(u.dias_vacaciones), 0), 0) AS cifra,
                  COALESCE(SUM(u.dias_vacaciones > 0), 0) AS personas,
                  ROUND(COALESCE(AVG(CASE WHEN u.dias_vacaciones > 0 THEN u.dias_vacaciones END), 0), 2)
                    AS promedio,
                  COALESCE(SUM(u.dias_vacaciones > %s), 0) AS pasan,
                  ROUND(COALESCE(MAX(u.dias_vacaciones), 0), 0) AS el_mas_alto
             FROM users u WHERE u.activo""", (umbral,))
    return {"cifra": f["cifra"],
            "detalle": {"personas": f["personas"], "promedio": f["promedio"],
                        "pasan_del_umbral": f["pasan"],
                        "umbral": int(umbral) if umbral == int(umbral) else umbral,
                        "el_mas_alto": f["el_mas_alto"]}}


async def _crecimiento(ajustes: dict) -> dict:
    meses = _entero(ajustes, "meses", 12)
    # Una fila por mes, del más antiguo al actual. generate_series de
    # PostgreSQL se arma aquí con una tabla de números.
    filas = await obtener_todos(
        """WITH RECURSIVE n AS (SELECT 0 AS k UNION ALL SELECT k + 1 FROM n WHERE k + 1 < %s),
                meses AS (SELECT DATE_FORMAT(CURRENT_DATE() - INTERVAL k MONTH, '%%Y-%%m-01') AS mes FROM n)
           SELECT DATE_FORMAT(m.mes, '%%Y-%%m') AS mes,
                  (SELECT COUNT(*) FROM users u
                    WHERE DATE_FORMAT(u.fecha_ingreso, '%%Y-%%m') = DATE_FORMAT(m.mes, '%%Y-%%m')) AS altas,
                  (SELECT COUNT(*) FROM users u
                    WHERE u.fecha_salida IS NOT NULL
                      AND DATE_FORMAT(u.fecha_salida, '%%Y-%%m') = DATE_FORMAT(m.mes, '%%Y-%%m')) AS bajas
             FROM meses m
            ORDER BY m.mes""", (max(meses, 1),))
    return {"cifra": sum(f["altas"] for f in filas) - sum(f["bajas"] for f in filas),
            "detalle": {"meses": [{"mes": f["mes"], "altas": f["altas"], "bajas": f["bajas"]}
                                  for f in filas]}}


async def _por_area(ajustes: dict) -> dict:
    cuantas = _entero(ajustes, "cuantas", 10)
    total = await obtener_uno(
        "SELECT COUNT(DISTINCT COALESCE(departamento, '(sin área)')) AS n FROM users WHERE activo")
    areas = await obtener_todos(
        """SELECT COALESCE(departamento, '(sin área)') AS area, COUNT(*) AS personas,
                  ROUND(COALESCE(SUM(dias_vacaciones), 0), 0) AS dias
             FROM users WHERE activo
            GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT %s""", (cuantas,))
    return {"cifra": total["n"], "detalle": {"areas": areas}}


async def _expedientes(_: dict) -> dict:
    f = await obtener_uno(
        """SELECT COALESCE(SUM(u.correo_pendiente OR u.jefe_id IS NULL
                               OR NOT COALESCE(u.ficha_completa, FALSE)), 0) AS cifra,
                  COALESCE(SUM(u.correo_pendiente), 0) AS sin_correo,
                  COALESCE(SUM(u.jefe_id IS NULL), 0) AS sin_jefe,
                  COALESCE(SUM(NOT COALESCE(u.ficha_completa, FALSE)), 0) AS incompleta,
                  COUNT(*) AS de
             FROM users u WHERE u.activo""")
    return {"cifra": f["cifra"],
            "detalle": {"sin_correo": f["sin_correo"], "sin_jefe": f["sin_jefe"],
                        "ficha_incompleta": f["incompleta"], "de": f["de"]}}


async def _papeles(_: dict) -> dict:
    f = await obtener_uno(
        """SELECT COALESCE(SUM(i.impresiones = 0), 0) AS cifra,
                  COALESCE(SUM(i.impresiones = 0 AND i.tipo = 'trazabilidad'), 0) AS trazabilidad,
                  COALESCE(SUM(i.impresiones = 0 AND i.tipo = 'solicitud'), 0) AS solicitud,
                  COUNT(*) AS emitidos
             FROM informes_firmados i""")
    return {"cifra": f["cifra"],
            "detalle": {"trazabilidad": f["trazabilidad"], "solicitud": f["solicitud"],
                        "emitidos": f["emitidos"]}}


CALCULOS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "ausentes_hoy": _ausentes_hoy, "activos": _activos, "por_aprobar": _por_aprobar,
    "sin_jefe": _sin_jefe, "pasivo": _pasivo, "crecimiento": _crecimiento,
    "por_area": _por_area, "expedientes": _expedientes, "papeles": _papeles,
}


async def tablero_indicadores(claves: list[str] | None = None) -> list[dict[str, Any]]:
    """[{clave, datos}] de los bloques encendidos, en su orden."""
    if claves is None:
        bloques = await obtener_todos(
            "SELECT clave, ajustes FROM tablero_bloques WHERE visible ORDER BY orden")
    else:
        bloques = await obtener_todos(
            "SELECT clave, ajustes FROM tablero_bloques WHERE visible AND clave IN %s ORDER BY orden",
            (lista(claves),))
    resultado = []
    for b in bloques:
        calculo = CALCULOS.get(b["clave"])
        # Un bloque sin cálculo se dice, no se calla: un hueco silencioso en
        # un tablero se lee como un cero.
        datos = (await calculo(b["ajustes"] or {}) if calculo
                 else {"cifra": None, "error": "Este indicador todavía no se calcula."})
        resultado.append({"clave": b["clave"], "datos": para_json(datos)})
    return resultado

