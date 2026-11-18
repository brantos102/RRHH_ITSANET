"""El historial de vacaciones de una persona, año por año.

Responde las preguntas de siempre —«¿cuántos días me dieron?, ¿cuántos
tomé?, ¿de dónde sale mi saldo?»— con lo que ya está registrado:

  · Días asignados: los de cada año de servicio (vacation_periods), según la
    antigüedad (Art. 69 CT: 15 días, y desde el sexto año uno más por año,
    hasta 15 adicionales). Cada año de servicio se cuenta en el año
    calendario en que se cumple; el que está en curso, con lo acumulado
    hasta hoy.
  · Días tomados: las vacaciones de la hoja de Talento Humano (antes del
    sistema), las aprobadas en el sistema y los permisos con cargo a
    vacaciones, en el año en que empezaron.
  · Saldo: el oficial de la ficha. Si no coincide con generados − tomados
    (ajustes de Talento Humano, días caducados, saldo inicial conciliado),
    se dice cuánto y por qué, en vez de esconder la diferencia.

Lo usan la pantalla, el Excel y el PDF: los tres dicen lo mismo.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..db import obtener_todos, obtener_uno

BASE = 15


def _num(v) -> float:
    return float(v or 0)


async def construir(user_id) -> dict[str, Any]:
    """Una línea de tiempo: cada año de servicio cumplido SUMA sus días (base
    + adicionales por antigüedad), cada vacación los RESTA, y cada movimiento
    dice cuántos quedan. Agrupada por año calendario."""
    persona = await obtener_uno(
        """SELECT u.id, u.nombre, u.cedula, u.cargo, u.departamento, u.fecha_ingreso, u.dias_vacaciones,
                  anios_cumplidos(u.fecha_ingreso) AS anios, cfg_int('vacaciones_dias_base') AS base
             FROM users u WHERE u.id = %s""", (str(user_id),))
    if persona is None:
        return {}
    base = int(persona["base"] or BASE)
    periodos = await obtener_todos(
        """SELECT p.periodo, p.fecha_desde, p.fecha_hasta, p.dias_asignados, p.devengado, p.caducado,
                  p.dias_saldo, p.vence_en, dias_por_antiguedad(p.periodo) AS esperado,
                  a.dias_laborables, a.dias_no_laborables
             FROM vacation_periods p
             LEFT JOIN v_antiguedad_referencia a
                    ON p.periodo BETWEEN a.anios_desde AND COALESCE(a.anios_hasta, 999)
            WHERE p.user_id = %s ORDER BY p.periodo""", (str(user_id),))
    tomas = await obtener_todos(
        """SELECT 'historico' AS origen, CAST(h.id AS CHAR) AS ref, NULL AS folio, h.fecha_inicio, h.fecha_fin,
                  h.dias, 'Registro de Talento Humano (antes del sistema)' AS detalle
             FROM vacaciones_historicas h WHERE h.user_id = %(u)s
           UNION ALL
           SELECT 'solicitud', r.id, r.folio, r.fecha_inicio, r.fecha_fin, r.dias_solicitados,
                  CASE WHEN r.tipo = 'vacacion' THEN 'Vacaciones solicitadas en el sistema'
                       ELSE CONCAT('Permiso con cargo a vacaciones: ', COALESCE(pt.nombre, 'permiso')) END
             FROM requests r LEFT JOIN permission_types pt ON pt.id = r.permission_type_id
            WHERE r.user_id = %(u)s AND r.estado IN ('aprobado', 'pendiente_anulacion')
              AND r.eliminada_en IS NULL
              AND (r.tipo = 'vacacion' OR COALESCE(pt.descuenta_vacaciones, FALSE))
            ORDER BY fecha_inicio""", {"u": str(user_id)})
    revisiones = await obtener_todos(
        """SELECT id, origen, historico_id, request_id, estado, respuesta, created_at, resuelto_en
             FROM refutaciones_historial WHERE user_id = %s ORDER BY id DESC""", (str(user_id),))
    revision_de: dict[tuple[str, str], dict] = {}
    for rv in revisiones:   # la más reciente manda
        clave = (rv["origen"], str(rv["historico_id"] if rv["origen"] == "historico" else rv["request_id"]))
        revision_de.setdefault(clave, rv)

    hoy = dt.date.today()
    eventos: list[dict[str, Any]] = []   # (fecha, orden) → asignaciones antes que tomas el mismo día
    periodos_info = []
    for p in periodos:
        esperado = int(p["esperado"] or 0)
        asignados = _num(p["dias_asignados"])
        info = {
            "periodo": int(p["periodo"]), "desde": p["fecha_desde"], "hasta": p["fecha_hasta"],
            "base": min(base, esperado) if esperado else base, "adicionales": max(esperado - base, 0),
            "total": esperado, "asignados": asignados, "devengado": bool(p["devengado"]),
            "caducado": bool(p["caducado"]),
            "laborables": p["dias_laborables"], "no_laborables": p["dias_no_laborables"],
            "nota": None,
        }
        # ¿Se registraron los días que manda la tabla (con los adicionales)?
        if p["devengado"] and abs(asignados - esperado) >= 0.01:
            info["nota"] = (f"Registrados {asignados:g}: faltan {esperado - asignados:g} día(s) de los {esperado} "
                            "que corresponden. Consulte a Talento Humano." if asignados < esperado else
                            f"Registrados {asignados:g}: {asignados - esperado:g} día(s) más que la tabla "
                            "(ajuste de Talento Humano).")
        periodos_info.append(info)
        cuando = p["fecha_hasta"] if p["devengado"] else hoy
        eventos.append({"tipo": "asignacion", "fecha": cuando, "orden": 0, "dias": asignados, "periodo": info})
        if p["caducado"] and _num(p["dias_saldo"]) > 0:
            eventos.append({"tipo": "caducidad", "fecha": p["vence_en"] or p["fecha_hasta"], "orden": 2,
                            "dias": -_num(p["dias_saldo"]), "periodo": info})
    for t in tomas:
        rv = revision_de.get((t["origen"], str(t["ref"])))
        eventos.append({"tipo": "toma", "fecha": t["fecha_inicio"], "orden": 1, "dias": -_num(t["dias"]),
                        "registro": {
                            "origen": t["origen"], "ref": str(t["ref"]),
                            "folio": int(t["folio"]) if t["folio"] else None,
                            "fecha_inicio": t["fecha_inicio"], "fecha_fin": t["fecha_fin"], "dias": _num(t["dias"]),
                            "detalle": t["detalle"],
                            "revision": ({"id": int(rv["id"]), "estado": rv["estado"], "respuesta": rv["respuesta"],
                                          "pedida_en": rv["created_at"], "resuelta_en": rv["resuelto_en"]}
                                         if rv else None)}})
    eventos.sort(key=lambda e: (e["fecha"], e["orden"]))

    anios: dict[int, dict[str, Any]] = {}
    saldo = 0.0
    for e in eventos:
        a = anios.get(e["fecha"].year)
        if a is None:
            a = anios[e["fecha"].year] = {
                "anio": e["fecha"].year, "saldo_inicio": round(saldo, 2), "base": 0, "adicionales": 0,
                "total": 0, "asignados": 0.0, "en_curso": False, "tomados": 0.0, "caducados": 0.0,
                "periodos": [], "registros": [], "movimientos": []}
        saldo += e["dias"]
        mov = {"tipo": e["tipo"], "fecha": e["fecha"], "dias": round(e["dias"], 2), "quedan": round(saldo, 2)}
        if e["tipo"] == "asignacion":
            per = e["periodo"]
            a["periodos"].append(per)
            a["asignados"] += e["dias"]
            if per["devengado"]:
                a["base"] += per["base"]
                a["adicionales"] += per["adicionales"]
                a["total"] += per["total"]
            else:
                a["en_curso"] = True
            mov.update({"periodo": per["periodo"], "base": per["base"], "adicionales": per["adicionales"],
                        "total": per["total"], "devengado": per["devengado"], "hasta": per["hasta"],
                        "nota": per["nota"]})
        elif e["tipo"] == "caducidad":
            a["caducados"] += -e["dias"]
            mov["periodo"] = e["periodo"]["periodo"]
        else:
            a["tomados"] += -e["dias"]
            mov["registro"] = len(a["registros"])
            reg = {**e["registro"], "quedan": round(saldo, 2)}
            a["registros"].append(reg)
        a["movimientos"].append(mov)
        a["saldo_cierre"] = round(saldo, 2)

    lista = []
    for a in sorted(anios.values(), key=lambda x: x["anio"]):
        a["asignados"] = round(a["asignados"], 2)
        a["tomados"] = round(a["tomados"], 2)
        a["caducados"] = round(a["caducados"], 2)
        # El balance del año: lo que le correspondió ese año menos lo que tomó.
        # Si el año de servicio en curso todavía no se cumple, cuenta lo
        # acumulado hasta hoy.
        cumplidos = sum(p["asignados"] for p in a["periodos"] if p["devengado"])
        a["asignados_del_anio"] = round(cumplidos if cumplidos else a["asignados"], 2)
        a["balance"] = round(a["asignados_del_anio"] - a["tomados"], 2)
        lista.append(a)

    generados = round(sum(a["asignados"] for a in lista), 2)
    tomados = round(sum(a["tomados"] for a in lista), 2)
    caducados = round(sum(a["caducados"] for a in lista), 2)
    saldo_oficial = round(_num(persona["dias_vacaciones"]), 2)
    actual = next((p for p in periodos_info if not p["devengado"]), periodos_info[-1] if periodos_info else None)
    return {
        "persona": {"nombre": persona["nombre"], "cedula": persona["cedula"], "cargo": persona["cargo"],
                    "departamento": persona["departamento"], "fecha_ingreso": persona["fecha_ingreso"],
                    "anios_servicio": int(persona["anios"] or 0)},
        "resumen": {"generados": generados, "tomados": tomados, "caducados": caducados, "saldo": saldo_oficial,
                    "diferencia": round(generados - tomados - caducados - saldo_oficial, 2),
                    "adicionales": sum(p["adicionales"] for p in periodos_info if p["devengado"]),
                    "con_diferencias": [p["periodo"] for p in periodos_info if p["nota"]],
                    "derecho_actual": actual and {k: actual[k] for k in
                                                  ("periodo", "base", "adicionales", "total", "laborables",
                                                   "no_laborables", "hasta", "asignados", "devengado")},
                    "revisiones_pendientes": sum(1 for r in revisiones if r["estado"] == "pendiente")},
        "anios": lista,
        "generado_en": dt.datetime.now(),
    }


def etiqueta_balance(balance: float) -> str:
    if balance < 0:
        n = abs(balance)
        return f"−{n:g} ({'Día adelantado' if n == 1 else 'Días adelantados'})"
    if balance > 0:
        return f"+{balance:g} ({'Día sobrante' if balance == 1 else 'Días sobrantes'})"
    return "0 (Balance exacto)"

