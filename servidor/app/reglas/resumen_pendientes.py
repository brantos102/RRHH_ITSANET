"""Resumen diario de lo que espera decisión, por correo.

Cada mañana de lunes a viernes (con la tarea diaria de las 06:50):

  · a cada JEFE (o jefe alterno) con solicitudes que esperan su decisión
    desde hace más de un día, un solo correo con la lista;
  · a cada persona de TALENTO HUMANO, lo de su sede: lo que espera a
    Talento Humano y lo que está atascado con el jefe (más de dos días,
    jefe sin correo, ausente o sin jefe), para que lo mueva.

Un correo al día por persona, como mucho: la clave única del aviso
(resumen:<persona>:<fecha>) impide repetirlo si la tarea corre dos veces.
"""
from __future__ import annotations

import datetime as dt
import logging
from html import escape
from typing import Any

from .. import correo
from ..config import get_settings
from ..db import ejecutar, obtener_todos

log = logging.getLogger("rrhh.resumen")

_SQL = """
SELECT r.id, r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin, r.jefe_id,
       COALESCE(r.region, 'sierra') AS region, u.nombre AS empleado,
       COALESCE(pt.nombre, IF(r.tipo = 'vacacion', 'Vacaciones', 'Permiso')) AS categoria,
       j.nombre AS jefe, j.email AS jefe_email,
       TIMESTAMPDIFF(HOUR, CASE WHEN r.estado = 'pendiente_rrhh' THEN COALESCE(r.jefe_aprobado_en, r.created_at)
                                ELSE COALESCE(r.rrhh_aprobado_en, r.created_at) END, NOW(6)) AS horas,
       (SELECT 1 FROM requests a WHERE a.user_id = r.jefe_id AND a.estado IN ('aprobado', 'pendiente_anulacion')
          AND a.eliminada_en IS NULL AND a.hora_inicio IS NULL
          AND CURRENT_DATE() BETWEEN a.fecha_inicio AND a.fecha_fin LIMIT 1) AS jefe_ausente
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN users j ON j.id = r.jefe_id
  LEFT JOIN permission_types pt ON pt.id = r.permission_type_id
 WHERE r.estado IN ('pendiente_jefe', 'pendiente_rrhh') AND r.eliminada_en IS NULL
 ORDER BY r.created_at
"""


def _hace(horas: int) -> str:
    return f"{horas // 24} día(s)" if horas >= 48 else f"{horas} h"


def _tabla(filas: list[dict[str, Any]], con_jefe: bool) -> tuple[str, str]:
    celdas, lineas = [], []
    for f in filas:
        rango = f"{f['fecha_inicio']:%d/%m}" + ("" if f["fecha_fin"] == f["fecha_inicio"] else f"–{f['fecha_fin']:%d/%m}")
        extra = f" · con {f['jefe'] or 'nadie (sin jefe)'}" if con_jefe else ""
        celdas.append(
            f'<tr><td style="padding:6px 8px 6px 0;font-size:13px;color:#64748b">Nº {f["folio"]}</td>'
            f'<td style="padding:6px 0;font-size:14px">{escape(f["empleado"])} · {escape(f["categoria"])} · {rango}'
            f'<br><span style="font-size:12px;color:#9a3412">espera hace {_hace(int(f["horas"] or 0))}'
            f'{escape(extra)}</span></td></tr>')
        lineas.append(f"Nº {f['folio']}: {f['empleado']} · {f['categoria']} · {rango} · "
                      f"espera hace {_hace(int(f['horas'] or 0))}{extra}")
    return ('<table role="presentation" style="width:100%;border-collapse:collapse">' + "".join(celdas) + "</table>",
            "\n".join(lineas))


async def _enviar_una_vez(persona: dict, titulo: str, html_lista: str, texto_lista: str, intro: str) -> bool:
    """Deja el aviso en la campana y manda el correo, una vez al día."""
    from ..notificaciones import _marco
    clave = f"resumen:{persona['id']}:{dt.date.today():%Y-%m-%d}"
    nuevo = await ejecutar(
        """INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, clave_dedupe, accion_url)
           VALUES (%s, 'solicitud_pendiente', 'advertencia', %s, %s, 'resumen', %s, '/dashboard.html#aprobaciones')
           ON DUPLICATE KEY UPDATE clave_dedupe = clave_dedupe""",
        (str(persona["id"]), titulo, intro, clave))
    if nuevo != 1 or not persona.get("email"):
        return False
    url = f"{get_settings().app_url.rstrip('/')}/dashboard.html#aprobaciones"
    cuerpo = (f'<p style="margin:0 0 14px;font-size:14px;color:#475569">Hola {escape(persona["nombre"])}: '
              f"{escape(intro)}</p>" + html_lista)
    try:
        await correo.enviar(persona["email"], titulo, f"{titulo}\n\n{intro}\n\n{texto_lista}\n\nRevíselas aquí:\n{url}\n",
                            _marco(titulo, cuerpo, ("Revisar ahora", url)))
        return True
    except Exception:  # noqa: BLE001 - un correo que falla no detiene a los demás
        log.exception("No salió el resumen de pendientes a %s", persona["nombre"])
        return False


async def enviar_resumen(hoy: dt.date | None = None) -> dict[str, int]:
    hoy = hoy or dt.date.today()
    if hoy.weekday() >= 5:
        return {"jefes": 0, "talento_humano": 0, "omitido": 1}
    pendientes = await obtener_todos(_SQL)

    # A cada jefe: lo suyo que lleva más de un día.
    por_jefe: dict[str, list[dict[str, Any]]] = {}
    for f in pendientes:
        if f["estado"] == "pendiente_jefe" and f["jefe_id"] and int(f["horas"] or 0) >= 20:
            por_jefe.setdefault(str(f["jefe_id"]), []).append(f)
    jefes = 0
    for jefe_id, filas in por_jefe.items():
        persona = {"id": jefe_id, "nombre": filas[0]["jefe"], "email": filas[0]["jefe_email"]}
        html_lista, texto_lista = _tabla(filas, con_jefe=False)
        jefes += await _enviar_una_vez(
            persona, f"Tiene {len(filas)} solicitud(es) esperando su decisión", html_lista, texto_lista,
            f"{len(filas)} solicitud(es) de su equipo esperan su decisión. Mientras no decida, la persona no sabe "
            "si puede contar con esos días.")

    # A Talento Humano: lo de su sede que espera a Talento Humano o está atascado con el jefe.
    equipo = await obtener_todos("SELECT id, nombre, email, region FROM v_rrhh_por_region")
    th = 0
    for persona in equipo:
        suyas = [f for f in pendientes if f["region"] == (persona["region"] or "sierra")]
        atascadas = [f for f in suyas if f["estado"] == "pendiente_jefe" and (
            not f["jefe_id"] or not f["jefe_email"] or f["jefe_ausente"] or int(f["horas"] or 0) >= 48)]
        en_th = [f for f in suyas if f["estado"] == "pendiente_rrhh"]
        if not atascadas and not en_th:
            continue
        html_a, texto_a = _tabla(en_th, con_jefe=False)
        html_b, texto_b = _tabla(atascadas, con_jefe=True)
        html_lista = ((f'<p style="margin:14px 0 6px;font-weight:600">Esperan a Talento Humano ({len(en_th)})</p>' + html_a)
                      if en_th else "") + \
                     ((f'<p style="margin:14px 0 6px;font-weight:600">Atascadas con el jefe ({len(atascadas)})</p>'
                       '<p style="margin:0 0 6px;font-size:12px;color:#64748b">Más de 2 días, jefe sin correo, ausente '
                       'o sin jefe. Puede recordarlas o reasignarlas.</p>' + html_b) if atascadas else "")
        texto_lista = ((f"Esperan a Talento Humano ({len(en_th)}):\n{texto_a}\n\n" if en_th else "")
                       + (f"Atascadas con el jefe ({len(atascadas)}):\n{texto_b}" if atascadas else ""))
        th += await _enviar_una_vez(
            persona, f"Resumen del día: {len(en_th)} por decidir, {len(atascadas)} atascada(s)",
            html_lista, texto_lista, "Esto es lo que necesita su atención hoy en su sede.")
    return {"jefes": jefes, "talento_humano": th}
