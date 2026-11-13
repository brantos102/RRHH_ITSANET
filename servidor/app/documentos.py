"""Los dos documentos de vacaciones, en PDF, con el formato de la empresa.

  · CONSTANCIA DE GOCE Y REGISTRO DE VACACIONES — el historial completo.
  · SOLICITUD, APROBACIÓN Y CONSTANCIA DE GOCE DE VACACIONES — una solicitud.

Reproducen las plantillas de Talento Humano (FORMATO_SOLICITUD_Y_CONSTANCIA_
DE_VACACIONES.xlsx y Plantilla_Constancia_Goce_Vacaciones_FLEXNET.xlsx): los
mismos títulos, secciones, textos y bloques de firma, con los logos y el pie
de contacto, pero llenos con los datos de cada colaborador.

Un solo formato —PDF— para todo: lo que se ve en pantalla, lo que se imprime
y lo que se adjunta al correo de Talento Humano es el mismo documento.

El contenido NO se calcula aquí: llega ya fotografiado desde la base, tal
como se emitió (informes_firmados.datos). Esta capa solo lo maqueta.
Reimprimir con los datos de hoy lo que se firmó con los de ayer sería
falsificar el documento.

Lo único que se decide al imprimir es quién firma por Talento Humano: la
cabeza del departamento de la sede por defecto, otro integrante si quien
imprime lo elige, o en blanco para firmar a mano.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

RECURSOS = Path(__file__).parent / "recursos"
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")

AZUL = colors.HexColor("#1F4E78")
CELESTE = colors.HexColor("#D9EAF7")
GRIS = colors.HexColor("#F3F6F9")
AMARILLO = colors.HexColor("#FFF2CC")
LINEA = colors.HexColor("#7F8C99")
TEXTO = colors.HexColor("#111111")

ANCHO = A4[0] - 30 * mm          # 15 mm de margen a cada lado


# ----------------------------------------------------------------- formato
def _t(valor: Any) -> str:
    """Texto escapado para Paragraph; el vacío queda vacío (se llena a mano)."""
    return "" if valor is None else escape(str(valor))


def _como_fecha(valor: Any) -> date | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _fecha(valor: Any, vacio: str = "") -> str:
    d = _como_fecha(valor)
    return f"{d:%d/%m/%Y}" if d else vacio


def _dias(valor: Any) -> str:
    if valor is None:
        return ""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return str(int(n)) if n == int(n) else f"{n:.2f}".replace(".", ",")


def _estilos() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=12.5,
                          textColor=TEXTO)
    return {
        "base": base,
        "just": ParagraphStyle("just", parent=base, alignment=TA_JUSTIFY),
        "centro": ParagraphStyle("centro", parent=base, alignment=TA_CENTER),
        "titulo": ParagraphStyle("titulo", parent=base, fontName="Helvetica-Bold", fontSize=12,
                                 leading=15, alignment=TA_CENTER),
        "titulo_banda": ParagraphStyle("tb", parent=base, fontName="Helvetica-Bold", fontSize=11.5,
                                       leading=14, textColor=colors.white, alignment=TA_CENTER),
        "banda": ParagraphStyle("banda", parent=base, fontName="Helvetica-Bold", fontSize=9.5,
                                textColor=colors.white),
        "banda_c": ParagraphStyle("banda_c", parent=base, fontName="Helvetica-Bold", fontSize=9.5,
                                  textColor=colors.white, alignment=TA_CENTER),
        "seccion": ParagraphStyle("seccion", parent=base, fontName="Helvetica-Bold", fontSize=9.5),
        "etiqueta": ParagraphStyle("etiqueta", parent=base, fontName="Helvetica-Bold", fontSize=8.5,
                                   leading=10.5),
        "celda": ParagraphStyle("celda", parent=base, fontSize=8.5, leading=10.5),
        "celda_c": ParagraphStyle("celda_c", parent=base, fontSize=8.5, leading=10.5,
                                  alignment=TA_CENTER),
        "cabeza_c": ParagraphStyle("cabeza_c", parent=base, fontName="Helvetica-Bold", fontSize=8.5,
                                   leading=10.5, alignment=TA_CENTER),
        "nota": ParagraphStyle("nota", parent=base, fontName="Helvetica-Oblique", fontSize=7.8,
                               leading=10, alignment=TA_JUSTIFY),
        "pie": ParagraphStyle("pie", parent=base, fontSize=7, leading=9,
                              textColor=colors.HexColor("#555555")),
        "folio": ParagraphStyle("folio", parent=base, fontSize=7.5, alignment=TA_RIGHT,
                                textColor=colors.HexColor("#555555")),
    }


def _imagen(nombre: str, alto: float) -> Image | Spacer:
    ruta = RECURSOS / nombre
    if not ruta.exists():
        return Spacer(1, alto)
    img = Image(str(ruta))
    proporcion = img.imageWidth / img.imageHeight
    img.drawHeight, img.drawWidth = alto, alto * proporcion
    return img


def _fecha_documento(informe: dict) -> date:
    """La fecha que se consigna en el documento: la elegida al imprimir (hoy,
    o una anterior justificada) o, si no se eligió, la de emisión."""
    return (_como_fecha(informe.get("fecha_documento")) or _como_fecha(informe.get("emitido_en"))
            or date.today())


def _nota_fecha(informe: dict) -> str:
    """Si la fecha consignada es anterior a la impresión, el pie lo dice."""
    if not informe.get("retroactiva"):
        return ""
    return (f" · Fecha consignada {_fecha(informe.get('fecha_documento'))}, impreso el "
            f"{date.today():%d/%m/%Y} (fecha anterior autorizada por Talento Humano)")


def _ciudad(d: dict) -> str:
    c = d.get("colaborador") or {}
    return (c.get("sede") or c.get("ciudad") or (d.get("empresa") or {}).get("ciudad") or "")


def _firmante_txt(firmante: dict | None) -> tuple[str, str]:
    if not firmante:
        return "", ""
    return firmante.get("nombre") or "", firmante.get("firma_como") or "Talento Humano"


def _pdf(historia: list, al_pie=None) -> bytes:
    memoria = io.BytesIO()
    doc = SimpleDocTemplate(memoria, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=(30 if al_pie else 14) * mm,
                            title="Documento de vacaciones", author="Talento Humano")
    doc.build(historia, onFirstPage=al_pie, onLaterPages=al_pie)
    return memoria.getvalue()


# ---------------------------------------------------------------------------
# 1 · CONSTANCIA DE GOCE Y REGISTRO DE VACACIONES
# ---------------------------------------------------------------------------
def constancia_de_goce(informe: dict, firmante: dict | None = None) -> bytes:
    d = informe["datos"]
    c, t = d["colaborador"], d.get("totales") or {}
    e = d.get("empresa") or {}
    gozadas = d.get("gozadas") or []
    s = _estilos()
    emitido = _fecha_documento(informe)

    cabecera = Table([[_imagen("logo_itsanet.png", 13 * mm), "", _imagen("logo_flexnet.png", 13 * mm)]],
                     colWidths=[70 * mm, ANCHO - 140 * mm, 70 * mm])
    cabecera.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "LEFT"), ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    historia: list = [
        cabecera, Spacer(1, 6 * mm),
        Paragraph("CONSTANCIA DE GOCE Y REGISTRO DE VACACIONES", s["titulo"]),
        Paragraph(f"Folio {_t(informe.get('folio'))}", s["folio"]),
        Spacer(1, 3 * mm),
        Paragraph(
            f"En la ciudad de <b>{_t(_ciudad(d).upper())}</b> a los <b>{emitido.day}</b> días del mes "
            f"de <b>{MESES[emitido.month - 1].upper()}</b> de <b>{emitido.year}</b>, comparecen por una "
            f"parte <b>{_t((e.get('razon_social') or '').upper())}</b> y por otra parte el/la "
            f"trabajador(a) <b>{_t((c.get('nombre') or '').upper())}</b>, portador(a) de la cédula de "
            f"ciudadanía No. <b>{_t(c.get('cedula'))}</b> quien mantiene relación laboral con la "
            f"empresa desde el <b>{_fecha(c.get('fecha_ingreso'))}</b>.", s["just"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "Por medio del presente documento, la Empresa deja constancia del registro de los "
            "períodos de vacaciones gozados por el/la trabajador(a) durante su relación laboral, de "
            "acuerdo con la información y documentación que reposa en los archivos administrativos, "
            "de Talento Humano y/o nómina de la Empresa.", s["just"]),
        Spacer(1, 4 * mm),
        Paragraph("1. REGISTRO DE VACACIONES GOZADAS", s["seccion"]),
        Spacer(1, 1.5 * mm),
    ]

    filas = [[Paragraph(x, s["cabeza_c"]) for x in
              ("Fecha de inicio", "Fecha de finalización", "Días gozados", "Observación")]]
    for g in gozadas:
        filas.append([Paragraph(_fecha(g.get("fecha_inicio")), s["celda_c"]),
                      Paragraph(_fecha(g.get("fecha_fin")), s["celda_c"]),
                      Paragraph(_dias(g.get("dias")), s["celda_c"]),
                      Paragraph(_t(g.get("observacion") or "N/A"), s["celda"])])
    if not gozadas:
        filas.append([Paragraph("Sin vacaciones registradas a la fecha de emisión.", s["celda_c"]),
                      "", "", ""])
    filas.append([Paragraph(f"<b>Total · {_t(t.get('veces', len(gozadas)))} registro(s)</b>", s["celda_c"]),
                  "", Paragraph(f"<b>{_dias(t.get('dias'))}</b>", s["celda_c"]),
                  Paragraph(f"Saldo disponible a la fecha de emisión: "
                            f"<b>{_dias((d.get('saldo') or {}).get('dias_disponibles'))} día(s)</b>",
                            s["celda"])])
    tabla = Table(filas, colWidths=[32 * mm, 32 * mm, 24 * mm, ANCHO - 88 * mm], repeatRows=1)
    estilo = [("GRID", (0, 0), (-1, -1), 0.6, LINEA),
              ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7E9EC")),
              ("BACKGROUND", (0, -1), (-1, -1), GRIS),
              ("SPAN", (0, -1), (1, -1)),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    if not gozadas:
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    tabla.setStyle(TableStyle(estilo))
    historia += [tabla, Spacer(1, 4 * mm),
                 Paragraph("2. CONSTANCIA", s["seccion"]), Spacer(1, 1.5 * mm)]
    for parrafo in (
        "Con base en los registros y documentos disponibles en los archivos de la Empresa, se deja "
        "constancia de los períodos de vacaciones detallados en el presente documento, "
        "correspondientes al tiempo de servicio del/la trabajador(a) hasta la fecha de emisión de "
        "esta constancia.",
        "El presente documento tiene como finalidad dejar formalmente registrado el historial de "
        "vacaciones gozadas y facilitar el control administrativo del saldo de vacaciones "
        "correspondiente al trabajador, sin que ello implique renuncia a derechos laborales que "
        "pudieren corresponderle conforme a la legislación vigente (Constitución de la República, "
        "Art. 326, numeral 2).",
        "El/la trabajador(a) manifiesta haber recibido la información contenida en el presente "
        "documento y podrá formular las observaciones que considere pertinentes respecto de las "
        "fechas o períodos registrados.",
    ):
        historia += [Paragraph(parrafo, s["just"]), Spacer(1, 2 * mm)]
    historia += [Spacer(1, 1 * mm),
                 Paragraph("Para constancia y aceptación de su contenido, firman las partes.", s["base"]),
                 Spacer(1, 4 * mm)]

    def bloque(titulo: str, filas_: list[tuple[str, str]]) -> Table:
        datos = [[Paragraph(titulo, s["cabeza_c"]), ""]] + [
            [Paragraph(f"{k}:", s["etiqueta"]), Paragraph(_t(v), s["celda"])] for k, v in filas_]
        b = Table(datos, colWidths=[18 * mm, ANCHO / 2 - 22 * mm],
                  rowHeights=[None] + [None] * (len(filas_) - 1) + [11 * mm])
        b.setStyle(TableStyle([("GRID", (0, 1), (-1, -1), 0.6, LINEA), ("SPAN", (0, 0), (1, 0)),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        return b

    nombre_th, cargo_th = _firmante_txt(firmante)
    firmas = Table([[
        bloque("JEFE INMEDIATO", [("Nombre", c.get("jefe")), ("Cargo", c.get("jefe_cargo")),
                                  ("C.I.", c.get("jefe_cedula")), ("Firma", "")]),
        bloque("TRABAJADOR/A", [("Nombre", c.get("nombre")), ("C.I.", c.get("cedula")),
                                ("Cargo", c.get("cargo")), ("Firma", "")]),
    ]], colWidths=[ANCHO / 2, ANCHO / 2])
    firmas.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    th = Table([[bloque("RESPONSABLE DE TALENTO HUMANO",
                        [("Nombre", nombre_th), ("Cargo", cargo_th), ("Firma", "")]), ""]],
               colWidths=[ANCHO / 2, ANCHO / 2])
    th.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    historia += [KeepTogether([firmas, Spacer(1, 5 * mm), th])]

    if informe.get("es_reemision"):
        historia += [Spacer(1, 3 * mm), Paragraph(
            f"Reemisión autorizada por {_t(informe.get('autorizado_por'))} · motivo: "
            f"{_t(informe.get('autorizacion_motivo'))}. La constancia anterior sigue siendo válida.",
            s["nota"])]

    pie_txt = (f"Folio {informe.get('folio') or ''} · Emitido el {_fecha(informe.get('emitido_en'))}"
               f"{_nota_fecha(informe)} · Documento para firma manuscrita; el ejemplar firmado se "
               "archiva en el expediente.")

    def al_pie(lienzo, _doc):
        lienzo.saveState()
        ruta = RECURSOS / "pie_contacto.png"
        if ruta.exists():
            ancho = ANCHO
            alto = ancho * 177 / 1600
            lienzo.drawImage(str(ruta), 15 * mm, 8 * mm, width=ancho, height=alto, mask="auto")
        lienzo.setFont("Helvetica", 6.5)
        lienzo.setFillColor(colors.HexColor("#666666"))
        lienzo.drawString(15 * mm, 5 * mm, pie_txt)
        lienzo.restoreState()

    return _pdf(historia, al_pie)


# ---------------------------------------------------------------------------
# 2 · SOLICITUD, APROBACIÓN Y CONSTANCIA DE GOCE DE VACACIONES
# ---------------------------------------------------------------------------
def solicitud_y_constancia(informe: dict, firmante: dict | None = None) -> bytes:
    d = informe["datos"]
    c, sol = d["colaborador"], d["solicitud"]
    ap = d.get("aprobaciones") or {}
    s = _estilos()
    col = ANCHO / 4

    def banda(texto: str, centrado: bool = False) -> Table:
        b = Table([[Paragraph(texto, s["banda_c" if centrado else "banda"])]], colWidths=[ANCHO])
        b.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return b

    def caja(texto: str, fondo=GRIS, estilo: str = "just") -> Table:
        b = Table([[Paragraph(texto, s[estilo])]], colWidths=[ANCHO])
        b.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fondo),
                               ("BOX", (0, 0), (-1, -1), 0.4, LINEA),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        return b

    def rejilla(filas: list[list], extras: list | None = None) -> Table:
        datos = []
        for f in filas:
            datos.append([Paragraph(f[0], s["etiqueta"]), Paragraph(f[1], s["celda"]),
                          Paragraph(f[2], s["etiqueta"]) if len(f) > 2 else "",
                          Paragraph(f[3], s["celda"]) if len(f) > 3 else ""])
        r = Table(datos, colWidths=[col * 1.05, col * 0.95, col * 1.05, col * 0.95])
        estilo = [("GRID", (0, 0), (-1, -1), 0.6, LINEA), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("BACKGROUND", (0, 0), (0, -1), CELESTE), ("BACKGROUND", (2, 0), (2, -1), CELESTE),
                  ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        r.setStyle(TableStyle(estilo + (extras or [])))
        return r

    titulo = Table([[Paragraph("SOLICITUD, APROBACIÓN Y CONSTANCIA DE GOCE DE VACACIONES",
                               s["titulo_banda"]), _imagen("logo_flexnet.png", 12 * mm)]],
                   colWidths=[ANCHO - 30 * mm, 30 * mm], rowHeights=[14 * mm])
    titulo.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))

    ordinarias = sol.get("clase") != "Adelantadas"
    aprobada = bool(sol.get("aprobada"))
    marca = lambda si: "( X )" if si else "(&nbsp;&nbsp;&nbsp;&nbsp;)"  # noqa: E731
    fecha_aprobacion = (_fecha((ap.get("rrhh") or {}).get("cuando")) if aprobada else "") or \
        "____/____/______"
    folio = sol.get("folio")

    historia: list = [
        titulo, Spacer(1, 2 * mm),
        caja("El presente documento tiene por objeto registrar la solicitud, aprobación y goce "
             "efectivo del período de vacaciones del colaborador, dejando constancia de las fechas "
             "autorizadas y de la reincorporación a sus actividades laborales."),
        Spacer(1, 2 * mm),
        banda("1. IDENTIFICACIÓN DEL COLABORADOR"),
        rejilla([
            ["Nombre del colaborador:", _t(c.get("nombre")), "Cédula:", _t(c.get("cedula"))],
            ["Cargo:", _t(c.get("cargo")), "Centro / Bodega:",
             _t(c.get("bodega") or c.get("centro_costo"))],
            ["Fecha de ingreso:", _fecha(c.get("fecha_ingreso")), "Área:", _t(c.get("departamento"))],
            ["Código:", f"Solicitud N.º {_t(folio)}" if folio else "",
             "Fecha de solicitud:", _fecha(sol.get("solicitada_en"))],
            ["Jefe inmediato:", _t(c.get("jefe")), "", ""],
        ], [("SPAN", (1, 4), (3, 4)), ("BACKGROUND", (1, 4), (3, 4), colors.white)]),
        Spacer(1, 2 * mm),
        banda("2. PROGRAMACIÓN Y APROBACIÓN"),
        rejilla([
            ["Fecha de inicio de vacaciones:", _fecha(sol.get("fecha_inicio")),
             "Días efectivamente gozados:", _dias(sol.get("dias"))],
            ["Fecha de finalización:", _fecha(sol.get("fecha_fin")),
             "Nombre del reemplazo:", _t(sol.get("reemplazo"))],
            ["Fecha de reintegro:", _fecha(sol.get("reintegro")), "Tipo:",
             f"Ordinarias {marca(ordinarias)}<br/>Adelantadas {marca(not ordinarias)}"],
        ]),
        banda("APROBACIÓN", centrado=True),
    ]
    estado = Table([[Paragraph(f"<b>Estado:</b> {marca(aprobada)} APROBADO&nbsp;&nbsp;&nbsp;&nbsp;"
                               f"{marca(not aprobada)} NO APROBADO", s["celda"]),
                     Paragraph(f"<b>Fecha de aprobación:</b> {fecha_aprobacion}", s["celda"])]],
                   colWidths=[ANCHO / 2, ANCHO / 2])
    estado.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA)]))
    jefe_ap, rrhh_ap = ap.get("jefe") or {}, ap.get("rrhh") or {}
    autorizaciones = " · ".join(x for x in (
        f"Jefe inmediato: {_t(jefe_ap.get('nombre'))} ({_fecha(jefe_ap.get('cuando'))})"
        if jefe_ap.get("nombre") else "",
        f"Talento Humano: {_t(rrhh_ap.get('nombre'))} ({_fecha(rrhh_ap.get('cuando'))})"
        if rrhh_ap.get("nombre") else "") if x)
    historia += [estado]
    if autorizaciones:
        historia += [Paragraph(f"Autorizado en el sistema por {autorizaciones}.", s["pie"])]

    historia += [
        Spacer(1, 2 * mm),
        banda("3. CONSTANCIA DE GOCE EFECTIVO DE VACACIONES"),
        caja(f"Yo <b>{_t(c.get('nombre'))}</b> con CI: <b>{_t(c.get('cedula'))}</b> declaro que he "
             "gozado efectivamente del período de vacaciones indicado en este documento, comprendido "
             f"desde el <b>{_fecha(sol.get('fecha_inicio'))}</b> hasta el "
             f"<b>{_fecha(sol.get('fecha_fin'))}</b>, por un total de <b>{_dias(sol.get('dias'))}</b> "
             "días, y que me reincorporé a mis actividades laborales el "
             f"<b>{_fecha(sol.get('reintegro'))}</b>. Asimismo, manifiesto que las fechas registradas "
             "corresponden a las vacaciones efectivamente disfrutadas y que recibo copia o constancia "
             "del presente registro."),
        Spacer(1, 2 * mm),
        banda("4. DECLARACIÓN Y FIRMAS"),
        caja("Las partes dejan constancia de que la información consignada en este documento es "
             "correcta y corresponde al período de vacaciones solicitado, autorizado y/o "
             "efectivamente gozado. El presente registro forma parte del expediente laboral del "
             "colaborador y se conservará como respaldo de la gestión y goce de vacaciones."),
        Spacer(1, 2 * mm),
        Paragraph(f"{_t(_ciudad(d)) or 'Ecuador'}, {_fecha_documento(informe).day} de "
                  f"{MESES[_fecha_documento(informe).month - 1]} de {_fecha_documento(informe).year}",
                  s["celda"]),
        Spacer(1, 2 * mm),
    ]

    def firma(titulo_: str, nombre: str, cargo: str = "") -> Table:
        filas = [[Paragraph(titulo_, s["banda_c"])],
                 [Spacer(1, 6 * mm)],
                 [Paragraph("Firma: ________________________________", s["celda"])],
                 [Paragraph(f"Nombre: {_t(nombre) or '______________________________'}", s["celda"])]]
        if cargo:
            filas.append([Paragraph(f"Cargo: {_t(cargo)}", s["celda"])])
        filas.append([Paragraph("Fecha: ____/____/______", s["celda"])])
        b = Table(filas, colWidths=[ANCHO / 2 - 6 * mm])
        b.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), AZUL),
                               ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
        return b

    nombre_th, cargo_th = _firmante_txt(firmante)
    fila1 = Table([[firma("COLABORADOR(A)", c.get("nombre") or ""),
                    firma("JEFE INMEDIATO", c.get("jefe") or "")]],
                  colWidths=[ANCHO / 2, ANCHO / 2])
    fila1.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    fila2 = Table([[firma("RECURSOS HUMANOS", nombre_th, cargo_th),
                    _imagen("logo_itsanet.png", 13 * mm)]],
                  colWidths=[ANCHO / 2, ANCHO / 2])
    fila2.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                               ("VALIGN", (1, 0), (1, 0), "BOTTOM")]))
    historia += [KeepTogether([fila1, Spacer(1, 4 * mm), fila2]), Spacer(1, 4 * mm),
                 caja("<b>NOTA DE CONTROL INTERNO:</b> Este documento debe completarse con las fechas "
                      "reales de goce y conservarse junto con los registros de vacaciones y demás "
                      "documentación laboral correspondiente. En caso de modificación o interrupción "
                      "del período autorizado, deberá dejarse constancia de la nueva fecha y de la "
                      "autorización correspondiente.", AMARILLO, "nota")]

    pie_txt = (f"Folio {informe.get('folio') or ''} · Emitido el {_fecha(informe.get('emitido_en'))}"
               f" · Impresión N.º {int(informe.get('impresiones') or 0) + 1}{_nota_fecha(informe)}")

    def al_pie(lienzo, _doc):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 6.5)
        lienzo.setFillColor(colors.HexColor("#666666"))
        lienzo.drawString(15 * mm, 6 * mm, pie_txt)
        lienzo.restoreState()

    return _pdf(historia, al_pie)


def armar(informe: dict, firmante: dict | None = None) -> bytes:
    """El documento que corresponda al tipo emitido, en PDF."""
    if informe["tipo"] == "trazabilidad":
        return constancia_de_goce(informe, firmante)
    return solicitud_y_constancia(informe, firmante)


def nombre_archivo(informe: dict) -> str:
    tipo = "constancia-goce" if informe["tipo"] == "trazabilidad" else "solicitud-vacaciones"
    return f"{tipo}-{informe.get('folio') or 'documento'}.pdf"
