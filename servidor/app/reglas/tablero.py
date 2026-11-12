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


async def _cuota_discapacidad(ajustes: dict) -> dict:
    try:
        porcentaje = float(ajustes.get("porcentaje", 4))
    except (TypeError, ValueError):
        porcentaje = 4.0
    f = await obtener_uno(
        """SELECT COALESCE(SUM(u.tiene_discapacidad), 0) AS con_discapacidad,
                  COALESCE(SUM(u.sustituto_discapacidad AND NOT u.tiene_discapacidad), 0) AS sustitutos,
                  COUNT(*) AS de
             FROM users u WHERE u.activo""")
    requeridas = int(-(-f["de"] * porcentaje // 100)) if f["de"] >= 25 else 0   # hacia arriba
    cuentan = int(f["con_discapacidad"]) + int(f["sustitutos"])
    return {"cifra": cuentan,
            "detalle": {"con_discapacidad": f["con_discapacidad"], "sustitutos": f["sustitutos"],
                        "requeridas": requeridas, "faltan": max(requeridas - cuentan, 0),
                        "porcentaje": porcentaje, "de": f["de"]}}


CALCULOS: dict[str, Callable[[dict], Awaitable[dict]]] = {
    "cuota_discapacidad": _cuota_discapacidad,
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



# ------------------------------------------------------------------ explorador
"""El explorador: una MEDIDA agrupada por una DIMENSIÓN, con filtros.

Es lo que en Power BI se arma arrastrando un campo a «valores» y otro a
«ejes». Aquí las medidas y las dimensiones son una lista cerrada: el SQL se
arma solo con piezas de estas tablas, nunca con texto que llegue del
navegador. Y todo es agregado: no hay dimensión «persona».
"""

# (origen, valor, fecha del hecho o None, descripción)
MEDIDAS: dict[str, dict[str, Any]] = {
    "personas": {"titulo": "Personas activas", "desde": "users u", "donde": "u.activo",
                 "valor": "COUNT(*)", "fecha": None},
    "saldo_dias": {"titulo": "Días de vacaciones por gozar", "desde": "users u", "donde": "u.activo",
                   "valor": "ROUND(SUM(u.dias_vacaciones), 1)", "fecha": None},
    "saldo_promedio": {"titulo": "Saldo promedio (días)", "desde": "users u", "donde": "u.activo",
                       "valor": "ROUND(AVG(u.dias_vacaciones), 1)", "fecha": None},
    "dias_gozados": {"titulo": "Días de vacaciones gozados",
                     "desde": "v_historial_vacaciones h JOIN users u ON u.id = h.user_id",
                     "donde": "TRUE", "valor": "ROUND(SUM(h.dias), 1)", "fecha": "h.fecha_inicio"},
    "solicitudes": {"titulo": "Solicitudes", "desde": "requests r JOIN users u ON u.id = r.user_id",
                    "donde": "TRUE", "valor": "COUNT(*)", "fecha": "DATE(r.created_at)"},
    "altas": {"titulo": "Ingresos (altas)", "desde": "users u", "donde": "u.fecha_ingreso IS NOT NULL",
              "valor": "COUNT(*)", "fecha": "u.fecha_ingreso"},
    "bajas": {"titulo": "Salidas (bajas)", "desde": "users u", "donde": "u.fecha_salida IS NOT NULL",
              "valor": "COUNT(*)", "fecha": "u.fecha_salida"},
}

DIMENSIONES: dict[str, dict[str, Any]] = {
    "total": {"titulo": "Total", "expr": "'Total'"},
    "sede": {"titulo": "Sede", "expr": "COALESCE(g.sede, u.region, 'Quito')"},
    "area": {"titulo": "Área", "expr": "COALESCE(NULLIF(TRIM(u.departamento), ''), '(sin área)')"},
    "ciudad": {"titulo": "Ciudad", "expr": "COALESCE(NULLIF(TRIM(u.ciudad), ''), '(sin ciudad)')"},
    "cargo": {"titulo": "Cargo", "expr": "COALESCE(NULLIF(TRIM(u.cargo), ''), '(sin cargo)')"},
    "contrato": {"titulo": "Tipo de contrato", "expr": "COALESCE(u.tipo_contrato, '(sin registrar)')"},
    "genero": {"titulo": "Género", "expr": "COALESCE(NULLIF(u.genero, ''), '(sin dato)')"},
    "antiguedad": {"titulo": "Antigüedad", "orden_propio": True, "expr": """CASE
        WHEN TIMESTAMPDIFF(YEAR, u.fecha_ingreso, CURRENT_DATE()) < 1 THEN '1. Menos de 1 año'
        WHEN TIMESTAMPDIFF(YEAR, u.fecha_ingreso, CURRENT_DATE()) <= 5 THEN '2. 1 a 5 años'
        WHEN TIMESTAMPDIFF(YEAR, u.fecha_ingreso, CURRENT_DATE()) <= 10 THEN '3. 6 a 10 años'
        WHEN TIMESTAMPDIFF(YEAR, u.fecha_ingreso, CURRENT_DATE()) <= 20 THEN '4. 11 a 20 años'
        ELSE '5. Más de 20 años' END"""},
    "rol": {"titulo": "Rol en el sistema", "expr": "u.rol"},
    "mes": {"titulo": "Mes", "orden_propio": True, "solo_con_fecha": True, "expr": None},
    "estado": {"titulo": "Estado de la solicitud", "solo": "solicitudes", "expr": "r.estado"},
    "tipo": {"titulo": "Vacaciones o permiso", "solo": "solicitudes",
             "expr": "IF(r.tipo = 'vacacion', 'Vacaciones', 'Permiso')"},
}

LIMITE_CATEGORIAS = 25


def catalogo_explorador() -> dict:
    return {
        "medidas": [{"clave": k, "titulo": v["titulo"], "con_periodo": v["fecha"] is not None}
                    for k, v in MEDIDAS.items()],
        "dimensiones": [{"clave": k, "titulo": v["titulo"],
                         "solo_con_periodo": bool(v.get("solo_con_fecha")),
                         "solo": v.get("solo")} for k, v in DIMENSIONES.items()],
    }


async def explorar(medida: str, dimension: str, filtros: dict) -> dict:
    """[{etiqueta, valor}] de la medida por la dimensión, ya filtrado."""
    import datetime as dt
    from ..errores import ReglaDeNegocio

    m = MEDIDAS.get(medida)
    d = DIMENSIONES.get(dimension)
    if m is None or d is None:
        raise ReglaDeNegocio("Medida o dimensión desconocida.")
    if d.get("solo") and d["solo"] != medida:
        raise ReglaDeNegocio(f"«{d['titulo']}» solo se usa con «{MEDIDAS[d['solo']]['titulo']}».")
    if d.get("solo_con_fecha") and m["fecha"] is None:
        raise ReglaDeNegocio(f"«{m['titulo']}» es una foto de hoy: no se reparte por mes. "
                             "Use Ingresos, Salidas, Solicitudes o Días gozados.")

    condiciones, params = [m["donde"]], []
    if filtros.get("sede"):
        condiciones.append("COALESCE(u.region, 'sierra') = %s")
        params.append(str(filtros["sede"])[:20])
    if filtros.get("area"):
        condiciones.append("u.departamento = %s")
        params.append(str(filtros["area"])[:120])
    desde = hasta = None
    if m["fecha"] is not None:
        hoy = dt.date.today()
        try:
            desde = dt.date.fromisoformat(filtros.get("desde") or "") 
        except ValueError:
            desde = (hoy.replace(day=1) - dt.timedelta(days=335)).replace(day=1)
        try:
            hasta = dt.date.fromisoformat(filtros.get("hasta") or "")
        except ValueError:
            hasta = hoy
        if desde > hasta:
            desde, hasta = hasta, desde
        if (hasta - desde).days > 3700:
            raise ReglaDeNegocio("El período puede abarcar hasta diez años.")
        condiciones.append(f"{m['fecha']} BETWEEN %s AND %s")
        params += [desde, hasta]
        if medida == "solicitudes" and filtros.get("tipo") in ("vacacion", "permiso"):
            condiciones.append("r.tipo = %s")
            params.append(filtros["tipo"])

    expr = d["expr"] if dimension != "mes" else f"DATE_FORMAT({m['fecha']}, '%%Y-%%m')"
    orden = "etiqueta" if d.get("orden_propio") else "valor DESC"
    filas = await obtener_todos(
        f"""SELECT {expr} AS etiqueta, {m['valor']} AS valor
              FROM {m['desde']}
              LEFT JOIN regiones g ON g.codigo = COALESCE(u.region, 'sierra')
             WHERE {' AND '.join(condiciones)}
             GROUP BY etiqueta
             ORDER BY {orden}""", tuple(params))
    datos = [{"etiqueta": str(f["etiqueta"]).split(". ", 1)[-1] if dimension == "antiguedad"
              else str(f["etiqueta"]), "valor": float(f["valor"] or 0)} for f in filas]
    if dimension == "mes" and desde:
        # Todos los meses del período, también los que no tuvieron nada: una
        # línea que salta de marzo a julio esconde los ceros.
        valores = {x["etiqueta"]: x["valor"] for x in datos}
        datos, mes = [], desde.replace(day=1)
        while mes <= hasta:
            clave = mes.strftime("%Y-%m")
            datos.append({"etiqueta": clave, "valor": valores.get(clave, 0.0)})
            mes = (mes.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    otros = None
    if len(datos) > LIMITE_CATEGORIAS and dimension not in ("mes", "antiguedad"):
        resto = datos[LIMITE_CATEGORIAS - 1:]
        datos = datos[:LIMITE_CATEGORIAS - 1]
        # Sumar promedios no tiene sentido: el resto de un promedio no se agrupa.
        if medida != "saldo_promedio":
            otros = {"etiqueta": f"Otros ({len(resto)})", "valor": round(sum(x["valor"] for x in resto), 1)}
            datos.append(otros)
    return {"medida": medida, "dimension": dimension, "titulo_medida": m["titulo"],
            "titulo_dimension": d["titulo"], "datos": datos,
            "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()} if desde else None,
            "total": round(sum(x["valor"] for x in datos), 1) if medida != "saldo_promedio" else None}
