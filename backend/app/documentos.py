"""Los dos papeles que el colaborador firma a mano y presenta en Talento Humano.

Se imprimen desde el navegador y no se generan como archivo: así ningún dato
personal queda en el disco del servidor ni viaja por correo (LOPDP, Art. 10,
minimización). El HTML va completo y sin pedir nada de fuera —ni tipografías,
ni hojas de estilo, ni imágenes—, porque estas pantallas se usan en una
bodega con la red caída y un papel que se imprime a medias no sirve.

El contenido NO se calcula aquí: llega ya fotografiado desde la base, tal
como se emitió. Esta capa solo lo maqueta. La diferencia importa: reimprimir
un informe de trazabilidad con los datos de hoy, cuando lo que se firmó decía
otra cosa, sería falsificar el documento.
"""
from __future__ import annotations

from datetime import date
from html import escape
from typing import Any

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def _e(valor: Any) -> str:
    """Escapado, y el vacío como una raya: un campo en blanco se rellena a mano."""
    if valor is None or valor == "":
        return "—"
    return escape(str(valor))


def _fecha(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, str):
        try:
            valor = date.fromisoformat(valor[:10])
        except ValueError:
            return escape(valor)
    return f"{valor:%d/%m/%Y}"


def _fecha_larga(valor: date | None = None) -> str:
    d = valor or date.today()
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _dias(valor: Any) -> str:
    """Días sin decimales cuando son enteros: «15», no «15.00»."""
    if valor is None:
        return "—"
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return escape(str(valor))
    return str(int(n)) if n == int(n) else f"{n:.2f}".replace(".", ",")


ESTILO = """
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:11pt/1.45 Georgia,'Times New Roman',serif;color:#111;background:#e9e9ee;
       padding:24px 12px}
  .hoja{width:210mm;min-height:297mm;margin:0 auto 18px;padding:16mm 15mm;
        background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.18)}
  h1{font-size:14pt;text-align:center;letter-spacing:.04em}
  h2{font-size:10.5pt;margin:14px 0 6px;padding:4px 7px;background:#1f2937;color:#fff;
     text-transform:uppercase;letter-spacing:.06em}
  .empresa{text-align:center;border-bottom:2px solid #111;padding-bottom:8px;margin-bottom:4px}
  .empresa .razon{font-size:13pt;font-weight:bold;letter-spacing:.06em}
  .empresa .dato{font-size:9pt;color:#444}
  .folio{text-align:right;font:9pt/1.3 monospace;color:#444;margin-bottom:10px}
  table{width:100%;border-collapse:collapse}
  .campos td{border:1px solid #9ca3af;padding:5px 7px;vertical-align:top}
  .campos td.r{width:26%;background:#f3f4f6;font-size:9pt;text-transform:uppercase;
               letter-spacing:.03em;color:#374151}
  .reg th{border:1px solid #9ca3af;padding:5px 6px;background:#e5e7eb;font-size:9pt;
          text-transform:uppercase;letter-spacing:.03em}
  .reg td{border:1px solid #9ca3af;padding:5px 6px;font-size:10pt}
  .reg td.n{text-align:center;font-variant-numeric:tabular-nums}
  .reg tfoot td{background:#f3f4f6;font-weight:bold}
  .parrafo{text-align:justify;margin:8px 0}
  .marca{display:inline-block;border:1.5px solid #111;width:13px;height:13px;
         text-align:center;line-height:11px;font-weight:bold;margin-right:4px}
  .opcion{white-space:nowrap;margin-right:10px;display:inline-block}
  .firmas{display:flex;gap:10mm;margin-top:16mm;page-break-inside:avoid}
  .firma{flex:1;text-align:center;font-size:9.5pt}
  .firma .linea{border-top:1px solid #111;margin-bottom:4px;padding-top:0}
  .firma .hueco{height:16mm}
  .firma .rol{text-transform:uppercase;letter-spacing:.04em;color:#374151;font-size:8.5pt}
  .nota{margin-top:12mm;border:1px solid #9ca3af;background:#f9fafb;padding:7px 9px;
        font-size:8.5pt;line-height:1.5;color:#374151;page-break-inside:avoid}
  .nota b{display:block;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
  .pie{margin-top:8mm;font-size:8.5pt;color:#6b7280;border-top:1px solid #d1d5db;padding-top:5px}
  .barra{position:sticky;top:0;width:210mm;margin:0 auto 14px;display:flex;gap:8px;
         align-items:center;font-family:system-ui,sans-serif;font-size:10pt}
  .barra button{font:inherit;font-weight:600;padding:9px 18px;border:0;border-radius:9px;
                background:#111827;color:#fff;cursor:pointer}
  .barra p{color:#374151}
  @media print{
    body{background:#fff;padding:0}
    .hoja{box-shadow:none;margin:0;width:auto;min-height:0;padding:0}
    .barra{display:none}
    @page{size:A4;margin:14mm 13mm}
  }
"""


def _encabezado(empresa: dict, titulo: str, folio: str, subtitulo: str = "") -> str:
    ruc = empresa.get("ruc")
    return f"""
  <div class="empresa">
    <div class="razon">{_e(empresa.get('razon_social'))}</div>
    {f'<div class="dato">RUC {_e(ruc)}</div>' if ruc else ''}
  </div>
  <div class="folio">Folio {_e(folio)}</div>
  <h1>{escape(titulo)}</h1>
  {f'<p style="text-align:center;font-size:9.5pt;color:#374151">{escape(subtitulo)}</p>' if subtitulo else ''}
"""


def _barra(que_es: str) -> str:
    return f"""
  <div class="barra">
    <button onclick="window.print()">Imprimir</button>
    <p>{escape(que_es)}</p>
  </div>
"""


def _firma(rol: str, nombre: str | None = None, pie: str = "") -> str:
    return f"""
    <div class="firma">
      <div class="hueco"></div>
      <div class="linea"></div>
      <div>{_e(nombre) if nombre else '&nbsp;'}</div>
      <div class="rol">{escape(rol)}</div>
      {f'<div style="font-size:8pt;color:#6b7280">{escape(pie)}</div>' if pie else ''}
    </div>
"""


def _documento(titulo_pagina: str, cuerpo: str, barra: str) -> str:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(titulo_pagina)}</title><style>{ESTILO}</style></head>
<body>{barra}<div class="hoja">{cuerpo}</div></body></html>
"""


# ---------------------------------------------------------------------------
# 1 · CONSTANCIA DE GOCE DE VACACIONES  (el informe de trazabilidad)
#
# El historial completo. Se emite una sola vez, se firma y se presenta: es el
# acta de que la empresa y el colaborador están de acuerdo en el punto de
# partida. Las filas dicen de dónde viene cada una —del archivo de Talento
# Humano o del sistema—, porque quien firma «15 días en marzo de 2019» tiene
# derecho a saber de dónde salió ese renglón.
# ---------------------------------------------------------------------------
def constancia_de_goce(informe: dict) -> str:
    d = informe["datos"]
    c, t = d["colaborador"], d["totales"]
    gozadas = d.get("gozadas") or []

    filas = "".join(f"""
        <tr><td class="n">{_fecha(g['fecha_inicio'])}</td>
            <td class="n">{_fecha(g['fecha_fin'])}</td>
            <td class="n">{_dias(g['dias'])}</td>
            <td>{_e(g.get('observacion'))}</td></tr>""" for g in gozadas)

    if not gozadas:
        filas = """
        <tr><td colspan="4" style="padding:14px;text-align:center;color:#6b7280">
          Sin vacaciones registradas a la fecha de emisión de este documento.
        </td></tr>"""

    cuerpo = f"""
  {_encabezado(d['empresa'], 'Constancia de goce de vacaciones', informe['folio'],
               'Registro histórico de vacaciones del colaborador')}

  <h2>1 · Identificación del colaborador</h2>
  <table class="campos">
    <tr><td class="r">Nombre</td><td colspan="3">{_e(c['nombre'])}</td></tr>
    <tr><td class="r">Cédula</td><td>{_e(c['cedula'])}</td>
        <td class="r">Fecha de ingreso</td><td>{_fecha(c['fecha_ingreso'])}</td></tr>
    <tr><td class="r">Cargo</td><td>{_e(c['cargo'])}</td>
        <td class="r">Años de servicio</td><td>{_e(c.get('anios_servicio'))}</td></tr>
    <tr><td class="r">Área</td><td>{_e(c['departamento'])}</td>
        <td class="r">Centro de costo</td><td>{_e(c.get('centro_costo'))}</td></tr>
    <tr><td class="r">Bodega / centro</td><td>{_e(c.get('bodega'))}</td>
        <td class="r">Jefe inmediato</td><td>{_e(c.get('jefe'))}</td></tr>
  </table>

  <h2>2 · Registro de vacaciones gozadas</h2>
  <table class="reg">
    <thead><tr>
      <th style="width:18%">Fecha de inicio</th>
      <th style="width:18%">Fecha de finalización</th>
      <th style="width:13%">Días gozados</th>
      <th>Observación</th>
    </tr></thead>
    <tbody>{filas}</tbody>
    <tfoot><tr>
      <td class="n" colspan="2">Total · {_e(t['veces'])} registro(s)</td>
      <td class="n">{_dias(t['dias'])}</td>
      <td>{_e(t['desde_la_hoja'])} del archivo de Talento Humano,
          {_e(t['en_el_sistema'])} tramitado(s) por el sistema</td>
    </tr></tfoot>
  </table>

  <h2>3 · Constancia</h2>
  <p class="parrafo">
    Quien suscribe declara haber revisado el registro que consta en el numeral 2
    y lo reconoce como el detalle de las vacaciones efectivamente gozadas hasta
    la fecha de emisión de este documento. A la misma fecha, su saldo registrado
    es de <b>{_dias(d['saldo']['dias_disponibles'])} día(s)</b>.
  </p>
  <p class="parrafo">
    Cualquier diferencia respecto de este registro debe comunicarse a Talento
    Humano antes de firmar. La firma de este documento no implica renuncia a
    derecho alguno: los derechos laborales son irrenunciables conforme al
    Art. 326, numeral 2, de la Constitución de la República del Ecuador.
  </p>

  <div class="firmas">
    {_firma('Jefe inmediato', c.get('jefe'))}
    {_firma('Trabajador', c['nombre'], f"C.C. {c['cedula']}")}
    {_firma('Responsable de Talento Humano')}
  </div>

  <div class="nota">
    <b>Nota de control interno</b>
    Este documento se emite una sola vez por colaborador. Una reemisión
    requiere autorización expresa de Talento Humano o de Administración, consta
    con folio propio y no invalida el ejemplar ya firmado.
    {('Reemisión autorizada por ' + _e(informe.get('autorizado_por')) +
      ' · motivo: ' + _e(informe.get('autorizacion_motivo')))
     if informe.get('es_reemision') else ''}
  </div>

  <div class="pie">
    {_e(d['empresa'].get('ciudad'))}, {_fecha_larga()} ·
    Emitido el {_fecha(informe['emitido_en'])} · Folio {_e(informe['folio'])} ·
    Documento para firma manuscrita; la copia firmada se archiva en el
    expediente del colaborador.
  </div>
"""
    return _documento(f"Constancia de goce · {c['nombre']}", cuerpo,
                      _barra("Imprímalo, fírmelo y preséntelo en Talento Humano."))


# ---------------------------------------------------------------------------
# 2 · SOLICITUD Y CONSTANCIA DE VACACIONES  (el informe de cada solicitud)
#
# Solo lo pedido en esa sesión. Se emite con cada solicitud y se firma a mano:
# eso es lo que confirma que quien pidió es la persona, y no un tercero que se
# quedó con la sesión abierta. Por eso la sección 4 es una declaración y no un
# acuse de recibo.
# ---------------------------------------------------------------------------
def solicitud_y_constancia(informe: dict) -> str:
    d = informe["datos"]
    c, s = d["colaborador"], d["solicitud"]
    ap = d.get("aprobaciones") or {}
    jefe_ap, rrhh_ap = ap.get("jefe") or {}, ap.get("rrhh") or {}

    def marca(activa: bool) -> str:
        return f'<span class="marca">{"X" if activa else "&nbsp;"}</span>'

    ordinarias = s["clase"] == "Ordinarias"
    aprobada = bool(s.get("aprobada"))

    cuerpo = f"""
  {_encabezado(d['empresa'], 'Solicitud y constancia de vacaciones', informe['folio'],
               f"Solicitud N.º {s['folio']}" if s.get('folio') else '')}

  <h2>1 · Identificación del colaborador</h2>
  <table class="campos">
    <tr><td class="r">Nombre</td><td colspan="3">{_e(c['nombre'])}</td></tr>
    <tr><td class="r">Cédula</td><td>{_e(c['cedula'])}</td>
        <td class="r">Fecha de ingreso</td><td>{_fecha(c['fecha_ingreso'])}</td></tr>
    <tr><td class="r">Cargo</td><td>{_e(c['cargo'])}</td>
        <td class="r">Área</td><td>{_e(c['departamento'])}</td></tr>
    <tr><td class="r">Centro / bodega</td><td>{_e(c.get('bodega') or c.get('centro_costo'))}</td>
        <td class="r">Fecha de solicitud</td><td>{_fecha(s.get('solicitada_en'))}</td></tr>
    <tr><td class="r">Jefe inmediato</td><td colspan="3">{_e(c.get('jefe'))}</td></tr>
  </table>

  <h2>2 · Programación y aprobación</h2>
  <table class="campos">
    <tr><td class="r">Fecha de inicio</td><td>{_fecha(s['fecha_inicio'])}</td>
        <td class="r">Días a gozar</td><td>{_dias(s['dias'])}</td></tr>
    <tr><td class="r">Fecha de finalización</td><td>{_fecha(s['fecha_fin'])}</td>
        <td class="r">Fecha de reintegro</td><td>{_fecha(s['reintegro'])}</td></tr>
    <tr><td class="r">Reemplazo en el puesto</td><td colspan="3">{_e(s.get('reemplazo'))}</td></tr>
    <tr><td class="r">Clase</td><td>
          <span class="opcion">{marca(ordinarias)} Ordinarias</span>
          <span class="opcion">{marca(not ordinarias)} Adelantadas</span></td>
        <td class="r">Estado</td><td>
          <span class="opcion">{marca(aprobada)} Aprobado</span>
          <span class="opcion">{marca(not aprobada)} No aprobado</span></td></tr>
    <tr><td class="r">Saldo al solicitar</td><td>{_dias(s.get('saldo_al_solicitar'))} día(s)</td>
        <td class="r">Autorizaciones</td><td>
          Jefatura: {_e(jefe_ap.get('nombre'))}{f" ({_fecha(jefe_ap.get('cuando'))})" if jefe_ap.get('cuando') else ''}<br>
          Talento Humano: {_e(rrhh_ap.get('nombre'))}{f" ({_fecha(rrhh_ap.get('cuando'))})" if rrhh_ap.get('cuando') else ''}
        </td></tr>
  </table>

  <h2>3 · Constancia de goce efectivo</h2>
  <p class="parrafo">
    Se deja constancia de que el colaborador identificado en el numeral 1 gozó
    efectivamente de las vacaciones programadas en el numeral 2, y se
    reincorporó a sus labores el {_fecha(s['reintegro'])}.
  </p>
  <table class="campos">
    <tr><td class="r">Fecha real de reintegro</td><td style="height:9mm"></td>
        <td class="r">Observación</td><td></td></tr>
  </table>

  <h2>4 · Declaración y firmas</h2>
  <p class="parrafo">
    Declaro que la presente solicitud fue formulada por mí, que los datos
    consignados son verdaderos y que conozco las fechas en que debo
    reincorporarme. Firmo de forma manuscrita para acreditar personalmente mi
    identidad ante Talento Humano.
  </p>

  <div class="firmas">
    {_firma('Colaborador', c['nombre'], f"C.C. {c['cedula']}")}
    {_firma('Jefe inmediato', c.get('jefe'))}
    {_firma('Talento Humano')}
  </div>

  <div class="nota">
    <b>Nota de control interno</b>
    Este formulario acompaña a la solicitud N.º {_e(s.get('folio'))} registrada
    en el sistema el {_fecha(s.get('solicitada_en'))}. La firma manuscrita del
    colaborador es el control que acredita que la solicitud no fue presentada
    por un tercero. Sin la copia firmada en el expediente, la solicitud consta
    registrada pero no verificada presencialmente.
  </div>

  <div class="pie">
    {_e(d['empresa'].get('ciudad'))}, {_fecha_larga()} ·
    Emitido el {_fecha(informe['emitido_en'])} · Folio {_e(informe['folio'])} ·
    Impresión N.º {_e(int(informe.get('impresiones') or 0) + 1)}
  </div>
"""
    return _documento(f"Solicitud de vacaciones · {c['nombre']}", cuerpo,
                      _barra("Imprímalo, fírmelo y preséntelo en Talento Humano "
                             "al retirar la autorización."))


def armar(informe: dict) -> str:
    """El documento que corresponda al tipo emitido."""
    if informe["tipo"] == "trazabilidad":
        return constancia_de_goce(informe)
    return solicitud_y_constancia(informe)
