"""El historial de vacaciones en Excel y PDF, para imprimirlo y revisarlo
con Talento Humano. Dice lo mismo que la pantalla (reglas/historial.py).

Lleva quién lo generó y cuándo, y la leyenda de datos personales (LOPDP):
el archivo sale del sistema y queda en el computador de quien lo descarga.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from fastapi import Response

from .db import ZONA_ECUADOR
from .exportar import AZUL_MARCA, LOGO, MIME
from .reglas.historial import etiqueta_balance

REVISION = {"pendiente": "En revisión por Talento Humano", "aceptada": "Revisión aceptada",
            "rechazada": "Revisión no aceptada"}


def _f(v) -> str:
    return v.strftime("%d/%m/%Y") if isinstance(v, (date, datetime)) else (str(v) if v is not None else "")


def _n(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def _nombre_archivo(datos: dict, ext: str) -> str:
    return f"historial-vacaciones-{datos['persona']['cedula']}-{date.today():%Y-%m-%d}.{ext}"


def _origen(r: dict) -> str:
    return f"Solicitud Nº {r['folio']}" if r["folio"] else "Hoja de Talento Humano"


def _nota_diferencia(res: dict) -> str:
    if not (res["caducados"] or res["diferencia"]):
        return ""
    texto = (f"Generados − tomados = {_n(round(res['generados'] - res['tomados'], 2))} días; "
             f"saldo oficial: {_n(res['saldo'])}.")
    if res["caducados"]:
        texto += f" {_n(res['caducados'])} día(s) caducaron."
    if res["diferencia"]:
        texto += (f" La diferencia de {_n(abs(res['diferencia']))} día(s) corresponde a ajustes de Talento Humano "
                  "o al saldo con que se cargó la ficha.")
    return texto


# ---------------------------------------------------------------------- Excel
def a_excel(datos: dict[str, Any], generado_por: str) -> Response:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    p, res = datos["persona"], datos["resumen"]
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Historial"
    azul = PatternFill("solid", fgColor=AZUL_MARCA)
    gris = PatternFill("solid", fgColor="E2E8F0")
    suave = PatternFill("solid", fgColor="F1F5F9")
    borde = Border(bottom=Side(style="thin", color="DDE3EA"))
    for col, ancho in zip("ABCDE", (16, 16, 14, 30, 30)):
        hoja.column_dimensions[col].width = ancho

    if LOGO.exists():
        try:
            from openpyxl.drawing.image import Image as ImagenXL
            logo = ImagenXL(str(LOGO))
            logo.height, logo.width = 36, int(36 * logo.width / logo.height)
            hoja.add_image(logo, "A1")
            hoja.row_dimensions[1].height = 30
        except Exception:  # noqa: BLE001
            pass
    hoja["C1"] = "Control de Vacaciones y Permisos"
    hoja["C1"].font = Font(size=14, bold=True, color=AZUL_MARCA)
    hoja.append([])
    for etiqueta, valor in (("Colaborador", p["nombre"]), ("Cédula", p["cedula"]),
                            ("Cargo y área", " · ".join(x for x in (p["cargo"], p["departamento"]) if x)),
                            ("Fecha de ingreso", _f(p["fecha_ingreso"])),
                            ("Años de servicio", p["anios_servicio"]),
                            ("Generado por", generado_por),
                            ("Generado el", datetime.now(ZONA_ECUADOR).strftime("%d/%m/%Y %H:%M"))):
        hoja.append([etiqueta, valor])
        hoja.cell(row=hoja.max_row, column=1).font = Font(bold=True)
    hoja.append([])
    hoja.append(["Días generados", "Días tomados", "Saldo actual"])
    fila = hoja.max_row
    for c in hoja[fila][:3]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), azul, Alignment(horizontal="center")
    hoja.append([res["generados"], res["tomados"], res["saldo"]])
    for c in hoja[hoja.max_row][:3]:
        c.font, c.alignment = Font(bold=True, size=13, color=AZUL_MARCA), Alignment(horizontal="center")
    nota = _nota_diferencia(res)
    if nota:
        hoja.append([nota])
        hoja.cell(row=hoja.max_row, column=1).font = Font(italic=True, color="64748B")

    for a in datos["anios"]:
        hoja.append([])
        titulo = f"Año {a['anio']}" + (" (en curso)" if a["en_curso"] else "")
        hoja.append([titulo, f"Asignados: {_n(a['asignados'])}", f"Tomados: {_n(a['tomados'])}",
                     etiqueta_balance(a["balance"])])
        for c in hoja[hoja.max_row][:5]:
            c.fill, c.font = gris, Font(bold=True)
        for per in a["periodos"]:
            hoja.append([f"Año de servicio {per['periodo']}",
                         f"{_f(per['desde'])} – {_f(per['hasta'])}",
                         f"{per['base']} + {per['adicionales']}",
                         "Acumulado hasta hoy" if not per["devengado"] else "Cumplido"
                         + (" · caducado" if per["caducado"] else "")])
            for c in hoja[hoja.max_row][:5]:
                c.font = Font(size=9, color="64748B")
        hoja.append(["Fecha de inicio", "Fecha de fin", "Días descontados", "Origen", "Revisión"])
        for c in hoja[hoja.max_row][:5]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
        for r in a["registros"]:
            hoja.append([_f(r["fecha_inicio"]), _f(r["fecha_fin"]), r["dias"], _origen(r),
                         REVISION.get((r["revision"] or {}).get("estado"), "")])
            for c in hoja[hoja.max_row][:5]:
                c.border = borde
            hoja.cell(row=hoja.max_row, column=3).alignment = Alignment(horizontal="center")
        if not a["registros"]:
            hoja.append(["Sin días tomados este año"])
        hoja.append(["", "Total días:", a["tomados"]])
        for c in hoja[hoja.max_row][:5]:
            c.fill, c.font = suave, Font(bold=True)
        hoja.cell(row=hoja.max_row, column=3).alignment = Alignment(horizontal="center")

    hoja.append([])
    hoja.append(["CONFIDENCIAL · Datos personales tratados conforme a la LOPDP del Ecuador."])
    hoja.cell(row=hoja.max_row, column=1).font = Font(size=8, color="94A3B8")
    hoja.page_setup.orientation = "portrait"
    hoja.page_setup.fitToWidth = 1
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.page_setup.fitToHeight = 0

    memoria = io.BytesIO()
    libro.save(memoria)
    return Response(memoria.getvalue(), media_type=MIME["xlsx"],
                    headers={"Content-Disposition": f'attachment; filename="{_nombre_archivo(datos, "xlsx")}"'})


# ------------------------------------------------------------------------ PDF
def a_pdf(datos: dict[str, Any], generado_por: str) -> Response:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as ImagenPDF
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    p, res = datos["persona"], datos["resumen"]
    azul = colors.HexColor(f"#{AZUL_MARCA}")
    tinta = colors.HexColor("#0f2a4a")
    memoria = io.BytesIO()
    doc = SimpleDocTemplate(memoria, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=13 * mm, bottomMargin=15 * mm,
                            title="Historial de vacaciones", author="Sistema de Permisos y Vacaciones")
    est = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=est["Heading1"], fontSize=16, textColor=tinta, alignment=1, spaceAfter=0)
    menor = ParagraphStyle("m", parent=est["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"))
    normal = ParagraphStyle("n", parent=est["Normal"], fontSize=9)
    cifra = ParagraphStyle("c", parent=est["Normal"], fontSize=20, leading=24, alignment=1,
                           textColor=azul, fontName="Helvetica-Bold")
    rotulo = ParagraphStyle("r", parent=est["Normal"], fontSize=7.5, alignment=1,
                            textColor=colors.HexColor("#475569"))
    ancho = doc.width

    piezas: list = []
    cab = [Paragraph("Control de Vacaciones y Permisos", titulo)]
    if LOGO.exists():
        from reportlab.lib.utils import ImageReader
        ancho_img, alto_img = ImageReader(str(LOGO)).getSize()
        alto = 9 * mm
        logo = ImagenPDF(str(LOGO), width=alto * ancho_img / alto_img, height=alto)
        cab = [logo, Paragraph("Control de Vacaciones y Permisos", titulo)]
    t = Table([cab], colWidths=[40 * mm, ancho - 40 * mm] if len(cab) == 2 else [ancho])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LINEBELOW", (0, 0), (-1, -1), 1.2, azul),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    piezas += [t, Spacer(1, 3 * mm)]
    datos_persona = (f"<b>{p['nombre']}</b> · C.I. {p['cedula']}"
                     + (f" · {p['cargo']}" if p["cargo"] else "")
                     + (f" · {p['departamento']}" if p["departamento"] else "")
                     + f"<br/>Ingreso: {_f(p['fecha_ingreso'])} · {p['anios_servicio']} año(s) de servicio")
    piezas += [Paragraph(datos_persona, normal), Spacer(1, 4 * mm)]

    resumen = Table([[Paragraph(_n(res["generados"]), cifra), Paragraph(_n(res["tomados"]), cifra),
                      Paragraph(_n(res["saldo"]), cifra)],
                     [Paragraph("DÍAS GENERADOS", rotulo), Paragraph("DÍAS TOMADOS", rotulo),
                      Paragraph("SALDO ACTUAL", rotulo)]], colWidths=[ancho / 3] * 3)
    resumen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#dde3ea")),
        ("LINEAFTER", (0, 0), (1, -1), 0.6, colors.HexColor("#dde3ea")),
        ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 1), (-1, 1), 8)]))
    piezas.append(resumen)
    nota = _nota_diferencia(res)
    if nota:
        piezas += [Spacer(1, 2 * mm), Paragraph(nota, menor)]
    piezas.append(Spacer(1, 5 * mm))

    color_badge = {-1: colors.HexColor("#ef4444"), 1: colors.HexColor("#10b981"), 0: colors.HexColor("#64748b")}
    blanco_b = ParagraphStyle("bb", parent=normal, fontSize=8, textColor=colors.white,
                              fontName="Helvetica-Bold", alignment=1)
    cab_anio = ParagraphStyle("ca", parent=normal, fontSize=12, textColor=azul, fontName="Helvetica-Bold")
    for a in datos["anios"]:
        signo = (a["balance"] > 0) - (a["balance"] < 0)
        encabezado = Table([[
            Paragraph(f"Año {a['anio']}" + (" <font size=8 color='#64748b'>(en curso)</font>" if a["en_curso"] else ""),
                      cab_anio),
            Paragraph(f"Asignados: {_n(a['asignados'])} &nbsp;|&nbsp; Tomados: {_n(a['tomados'])}", normal),
            Paragraph(etiqueta_balance(a["balance"]), blanco_b)]],
            colWidths=[ancho * 0.3, ancho * 0.4, ancho * 0.3])
        encabezado.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#f1f5f9")),
            ("BACKGROUND", (2, 0), (2, 0), color_badge[signo]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        servicio = "; ".join(
            f"año de servicio {per['periodo']} ({_f(per['desde'])} – {_f(per['hasta'])}): "
            f"{per['base']} base + {per['adicionales']} adicionales"
            + (" · acumulado hasta hoy" if not per["devengado"] else "")
            + (" · caducado" if per["caducado"] else "")
            for per in a["periodos"])
        filas = [["FECHA DE INICIO", "FECHA DE FIN", "DÍAS DESCONTADOS", "ORIGEN"]]
        for r in a["registros"]:
            origen = _origen(r) + (f"\n{REVISION[r['revision']['estado']]}" if r["revision"] else "")
            filas.append([_f(r["fecha_inicio"]), _f(r["fecha_fin"]), _n(r["dias"]), origen])
        if not a["registros"]:
            filas.append(["Sin días tomados este año", "", "", ""])
        filas.append(["", "Total días:", _n(a["tomados"]), ""])
        detalle = Table(filas, colWidths=[ancho * 0.22, ancho * 0.22, ancho * 0.2, ancho * 0.36], repeatRows=1)
        detalle.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e2e8f0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f8fafc")]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ("ALIGN", (1, -1), (1, -1), "RIGHT"),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1"))]))
        bloque = [encabezado]
        if servicio:
            bloque.append(Paragraph(servicio[0].upper() + servicio[1:], menor))
        bloque += [detalle, Spacer(1, 5 * mm)]
        piezas.append(KeepTogether(bloque))

    def pie(lienzo, d):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 7)
        lienzo.setFillColor(colors.HexColor("#94a3b8"))
        lienzo.drawString(15 * mm, 8 * mm,
                          f"Generado por {generado_por} el {datetime.now(ZONA_ECUADOR):%d/%m/%Y %H:%M} · "
                          "CONFIDENCIAL · Datos personales tratados conforme a la LOPDP del Ecuador.")
        lienzo.drawRightString(d.pagesize[0] - 15 * mm, 8 * mm, f"Página {d.page}")
        lienzo.restoreState()

    doc.build(piezas, onFirstPage=pie, onLaterPages=pie)
    return Response(memoria.getvalue(), media_type=MIME["pdf"],
                    headers={"Content-Disposition": f'attachment; filename="{_nombre_archivo(datos, "pdf")}"'})
