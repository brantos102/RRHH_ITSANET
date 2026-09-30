"""Descarga de informes en CSV, Excel y PDF.

Un solo lugar para los tres formatos: cada informe declara sus columnas y sus
filas, y de ahí salen los tres archivos. Lo que se exporta es exactamente lo
que se está viendo en pantalla, con el filtro aplicado escrito en el propio
documento: un informe que no dice de qué está hablando no sirve para
sustentar nada.

Protección de datos (LOPDP): estos archivos salen del sistema y quedan en el
computador de quien los descarga, así que llevan la marca de quién los generó
y cuándo. La decisión de qué columnas incluye cada informe es de quien lo
define; aquí no se añade nada por cuenta propia.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Sequence

from fastapi import Response

MIME = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@dataclass
class Informe:
    """Lo que hace falta para armar cualquiera de los tres formatos."""

    titulo: str
    columnas: Sequence[tuple[str, str]]      # (clave, etiqueta)
    filas: Sequence[dict]
    # El filtro con el que se obtuvo, en claro: sin esto el archivo no
    # significa nada dentro de tres meses.
    filtros: Sequence[tuple[str, str]] = field(default_factory=list)
    generado_por: str = ""
    nota: str = ""


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return str(valor)


def _nombre(titulo: str, extension: str) -> str:
    base = "".join(c if c.isalnum() or c in "-_ " else "" for c in titulo).strip()
    base = base.replace(" ", "-").lower() or "informe"
    return f"{base}-{date.today():%Y-%m-%d}.{extension}"


def _cabecera(informe: Informe, extension: str) -> dict[str, str]:
    return {"Content-Disposition":
            f'attachment; filename="{_nombre(informe.titulo, extension)}"'}


# ------------------------------------------------------------------------ CSV
def a_csv(informe: Informe) -> Response:
    memoria = io.StringIO()
    # Punto y coma: Excel en configuración regional española abre con coma los
    # archivos separados por coma y deja todo en una columna.
    escritor = csv.writer(memoria, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    escritor.writerow([informe.titulo])
    for etiqueta, valor in informe.filtros:
        escritor.writerow([etiqueta, valor])
    if informe.generado_por:
        escritor.writerow(["Generado por", informe.generado_por])
    escritor.writerow(["Generado el", datetime.now().strftime("%d/%m/%Y %H:%M")])
    # La nota, arriba y en los tres formatos. Solo salía en el PDF, y es
    # justo lo que tiene que viajar con el archivo: dice qué NO contiene
    # —importes, jornadas sin cerrar— y esa advertencia no puede quedarse en
    # el correo que lo acompañaba, porque el archivo se reenvía solo.
    if informe.nota:
        escritor.writerow(["Nota", informe.nota])
    escritor.writerow([])

    escritor.writerow([etiqueta for _, etiqueta in informe.columnas])
    for fila in informe.filas:
        escritor.writerow([_texto(fila.get(clave)) for clave, _ in informe.columnas])

    # BOM: sin él, Excel en Windows abre los acentos como símbolos.
    datos = "﻿" + memoria.getvalue()
    return Response(content=datos, media_type=MIME["csv"],
                    headers=_cabecera(informe, "csv"))


# ---------------------------------------------------------------------- Excel
def a_excel(informe: Informe) -> Response:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    hoja = libro.active
    hoja.title = informe.titulo[:31] or "Informe"   # Excel no admite más de 31

    hoja.append([informe.titulo])
    hoja["A1"].font = Font(size=14, bold=True)
    for etiqueta, valor in informe.filtros:
        hoja.append([etiqueta, valor])
    if informe.generado_por:
        hoja.append(["Generado por", informe.generado_por])
    hoja.append(["Generado el", datetime.now().strftime("%d/%m/%Y %H:%M")])
    if informe.nota:
        hoja.append(["Nota", informe.nota])
    hoja.append([])

    fila_cabecera = hoja.max_row + 1
    hoja.append([etiqueta for _, etiqueta in informe.columnas])
    relleno = PatternFill("solid", fgColor="0F172A")
    for celda in hoja[fila_cabecera]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno
        celda.alignment = Alignment(vertical="center")

    for fila in informe.filas:
        hoja.append([_texto(fila.get(clave)) for clave, _ in informe.columnas])

    # Ancho por contenido: una tabla con todas las columnas del mismo ancho
    # obliga a ajustarlas a mano antes de poder leerla.
    for i, (clave, etiqueta) in enumerate(informe.columnas, start=1):
        ancho = max(len(etiqueta),
                    *(len(_texto(f.get(clave))) for f in informe.filas[:200]), 8)
        hoja.column_dimensions[get_column_letter(i)].width = min(ancho + 2, 48)

    # Fija la cabecera y activa los filtros de Excel: es lo primero que hace
    # quien recibe una tabla larga.
    hoja.freeze_panes = hoja.cell(row=fila_cabecera + 1, column=1)
    hoja.auto_filter.ref = (
        f"A{fila_cabecera}:"
        f"{get_column_letter(len(informe.columnas))}{hoja.max_row}")

    memoria = io.BytesIO()
    libro.save(memoria)
    return Response(content=memoria.getvalue(), media_type=MIME["xlsx"],
                    headers=_cabecera(informe, "xlsx"))


# ------------------------------------------------------------------------ PDF
def a_pdf(informe: Informe) -> Response:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    memoria = io.BytesIO()
    # Apaisado: estas tablas tienen doce columnas y en vertical no entran.
    documento = SimpleDocTemplate(
        memoria, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title=informe.titulo, author="Sistema de Permisos y Vacaciones",
    )

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Heading1"],
                            fontSize=15, spaceAfter=2, textColor=colors.HexColor("#0f172a"))
    menor = ParagraphStyle("menor", parent=estilos["Normal"],
                           fontSize=8, textColor=colors.HexColor("#64748b"))
    celda = ParagraphStyle("celda", parent=estilos["Normal"], fontSize=7.2, leading=9)
    celda_cab = ParagraphStyle("celdacab", parent=celda, textColor=colors.white,
                               fontName="Helvetica-Bold")

    piezas: list = [Paragraph(informe.titulo, titulo)]
    linea = " · ".join(f"{e}: {v}" for e, v in informe.filtros) or "Sin filtros"
    piezas.append(Paragraph(linea, menor))
    pie = f"{len(informe.filas)} registro(s) · {datetime.now():%d/%m/%Y %H:%M}"
    if informe.generado_por:
        pie += f" · generado por {informe.generado_por}"
    piezas.append(Paragraph(pie, menor))
    if informe.nota:
        piezas.append(Spacer(1, 3 * mm))
        piezas.append(Paragraph(informe.nota, menor))
    piezas.append(Spacer(1, 5 * mm))

    # Los textos largos van en Paragraph para que partan de línea; con cadenas
    # sueltas, una descripción larga desborda la columna y tapa la siguiente.
    datos = [[Paragraph(etiqueta, celda_cab) for _, etiqueta in informe.columnas]]
    for fila in informe.filas:
        datos.append([Paragraph(_texto(fila.get(clave)).replace("&", "&amp;")
                                .replace("<", "&lt;"), celda)
                      for clave, _ in informe.columnas])

    ancho_util = documento.width
    tabla = Table(datos, repeatRows=1,
                  colWidths=[ancho_util / len(informe.columnas)] * len(informe.columnas))
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dde3ea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f6f8fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    piezas.append(tabla)

    def pie_de_pagina(lienzo, doc):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 7)
        lienzo.setFillColor(colors.HexColor("#94a3b8"))
        lienzo.drawString(
            12 * mm, 8 * mm,
            "Documento con datos personales. Tratamiento conforme a la Ley Orgánica "
            "de Protección de Datos Personales del Ecuador.")
        lienzo.drawRightString(doc.pagesize[0] - 12 * mm, 8 * mm, f"Página {doc.page}")
        lienzo.restoreState()

    documento.build(piezas, onFirstPage=pie_de_pagina, onLaterPages=pie_de_pagina)
    return Response(content=memoria.getvalue(), media_type=MIME["pdf"],
                    headers=_cabecera(informe, "pdf"))


def entregar(informe: Informe, formato: str) -> Response:
    """Devuelve el informe en el formato pedido."""
    if formato == "xlsx":
        return a_excel(informe)
    if formato == "pdf":
        return a_pdf(informe)
    return a_csv(informe)
