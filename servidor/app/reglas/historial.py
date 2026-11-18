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
    persona = await obtener_uno(
        """SELECT u.id, u.nombre, u.cedula, u.cargo, u.departamento, u.fecha_ingreso, u.dias_vacaciones,
                  anios_cumplidos(u.fecha_ingreso) AS anios
             FROM users u WHERE u.id = %s""", (str(user_id),))
    if persona is None:
        return {}
    periodos = await obtener_todos(
        """SELECT periodo, fecha_desde, fecha_hasta, dias_asignados, dias_consumidos, devengado, caducado,
                  dias_saldo
             FROM vacation_periods WHERE user_id = %s ORDER BY periodo""", (str(user_id),))
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

    anios: dict[int, dict[str, Any]] = {}

    def anio(a: int) -> dict[str, Any]:
        return anios.setdefault(a, {"anio": a, "asignados": 0.0, "tomados": 0.0, "en_curso": False,
                                    "caducados": 0.0, "periodos": [], "registros": []})

    for p in periodos:
        a = anio(p["fecha_hasta"].year)
        asignados = _num(p["dias_asignados"])
        a["asignados"] += asignados
        a["en_curso"] = a["en_curso"] or not p["devengado"]
        if p["caducado"]:
            a["caducados"] += max(_num(p["dias_saldo"]), 0)
        completo = BASE + max(0, min(15, int(p["periodo"]) - 5))
        a["periodos"].append({
            "periodo": int(p["periodo"]), "desde": p["fecha_desde"], "hasta": p["fecha_hasta"],
            "asignados": asignados, "devengado": bool(p["devengado"]), "caducado": bool(p["caducado"]),
            "base": BASE, "adicionales": completo - BASE, "al_cumplirse": completo,
        })

    for t in tomas:
        a = anio(t["fecha_inicio"].year)
        dias = _num(t["dias"])
        a["tomados"] += dias
        rv = revision_de.get((t["origen"], str(t["ref"])))
        a["registros"].append({
            "origen": t["origen"], "ref": str(t["ref"]), "folio": int(t["folio"]) if t["folio"] else None,
            "fecha_inicio": t["fecha_inicio"], "fecha_fin": t["fecha_fin"], "dias": dias, "detalle": t["detalle"],
            "revision": ({"id": int(rv["id"]), "estado": rv["estado"], "respuesta": rv["respuesta"],
                          "pedida_en": rv["created_at"], "resuelta_en": rv["resuelto_en"]} if rv else None),
        })

    lista = []
    for a in sorted(anios.values(), key=lambda x: x["anio"]):
        a["asignados"] = round(a["asignados"], 2)
        a["tomados"] = round(a["tomados"], 2)
        a["balance"] = round(a["asignados"] - a["tomados"], 2)
        lista.append(a)

    generados = round(sum(a["asignados"] for a in lista), 2)
    tomados = round(sum(a["tomados"] for a in lista), 2)
    caducados = round(sum(a["caducados"] for a in lista), 2)
    saldo = round(_num(persona["dias_vacaciones"]), 2)
    diferencia = round(generados - tomados - caducados - saldo, 2)
    return {
        "persona": {"nombre": persona["nombre"], "cedula": persona["cedula"], "cargo": persona["cargo"],
                    "departamento": persona["departamento"], "fecha_ingreso": persona["fecha_ingreso"],
                    "anios_servicio": int(persona["anios"] or 0)},
        "resumen": {"generados": generados, "tomados": tomados, "caducados": caducados, "saldo": saldo,
                    "diferencia": diferencia,
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

