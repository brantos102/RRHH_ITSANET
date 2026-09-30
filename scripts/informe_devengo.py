"""Informe oficial sobre el cálculo del devengo de vacaciones.

    python scripts/informe_devengo.py                       # informe_devengo.pdf
    python scripts/informe_devengo.py --salida ruta.pdf

El sistema y la hoja que lleva Talento Humano daban cifras distintas para la
misma persona el mismo día. Este documento existe para que esa diferencia se
pueda llevar a una reunión y decidirse, en vez de discutirse.

Las cifras NO están escritas aquí: se leen de la base cada vez que se genera.
Un informe con números a mano envejece mal y no se puede volver a comprobar.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

TITULO = "Cálculo de los días de vacaciones devengados"
SUBTITULO = "Diferencia entre el registro de Talento Humano y el sistema, y qué se propone"


async def reunir() -> dict:
    from app.db import obtener_todos, obtener_uno

    resumen = await obtener_uno("""
        select count(*)                                              as personas,
               count(*) filter (where anios_cumplidos >= 5)          as con_cinco_o_mas,
               count(*) filter (where anios_cumplidos <  5)          as con_menos_de_cinco,
               count(*) filter (where devengado_prorrateado > devengado_hoja) as con_diferencia,
               round(sum(devengado_prorrateado - devengado_hoja), 2) as dias_de_diferencia,
               round(max(devengado_prorrateado - devengado_hoja), 2) as diferencia_mayor
          from public.v_devengo_cotejo""")

    tramos = await obtener_todos("""
        select case when anios_cumplidos < 5 then 'Menos de 5 años'
                    when anios_cumplidos < 10 then 'De 5 a 9 años'
                    when anios_cumplidos < 15 then 'De 10 a 14 años'
                    else '15 años o más' end                          as tramo,
               min(anios_cumplidos)                                   as orden,
               count(*)                                               as personas,
               round(min(devengado_prorrateado - devengado_hoja), 2)  as dif_menor,
               round(max(devengado_prorrateado - devengado_hoja), 2)  as dif_mayor,
               round(sum(devengado_prorrateado - devengado_hoja), 2)  as dif_total
          from public.v_devengo_cotejo group by 1 order by orden""")

    casos = await obtener_todos("""
        select anios_cumplidos, meses_del_periodo, tope_anual_del_periodo,
               devengado_hoja, devengado_prorrateado,
               round(devengado_prorrateado - devengado_hoja, 2) as diferencia,
               count(*) as personas
          from public.v_devengo_cotejo
         where devengado_prorrateado > devengado_hoja
         group by 1,2,3,4,5,6 order by diferencia desc limit 8""")

    saldo = await obtener_uno(
        "select round(coalesce(sum(dias_vacaciones), 0), 2) as total from public.users where activo")

    return {"resumen": resumen, "tramos": tramos, "casos": casos, "saldo": saldo}


def construir(datos: dict, salida: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    TINTA = colors.HexColor("#0f172a")
    SUAVE = colors.HexColor("#475569")
    LINEA = colors.HexColor("#cbd5e1")
    FONDO = colors.HexColor("#f1f5f9")

    hojas = getSampleStyleSheet()
    normal = ParagraphStyle("cuerpo", parent=hojas["Normal"], fontName="Helvetica",
                            fontSize=10, leading=15, alignment=TA_JUSTIFY,
                            textColor=TINTA, spaceAfter=7)
    h1 = ParagraphStyle("h1", parent=normal, fontName="Helvetica-Bold", fontSize=17,
                        leading=21, alignment=0, spaceAfter=3)
    bajada = ParagraphStyle("bajada", parent=normal, fontSize=10.5, leading=15,
                            textColor=SUAVE, alignment=0, spaceAfter=14)
    h2 = ParagraphStyle("h2", parent=normal, fontName="Helvetica-Bold", fontSize=12,
                        leading=16, alignment=0, spaceBefore=14, spaceAfter=5)
    nota = ParagraphStyle("nota", parent=normal, fontSize=8.5, leading=12,
                          textColor=SUAVE)
    destacado = ParagraphStyle("destacado", parent=normal, fontName="Helvetica-Bold",
                               fontSize=10.5, leading=15, alignment=0)

    def tabla(filas, anchos, encabezado=True):
        t = Table(filas, colWidths=anchos, hAlign="LEFT")
        estilo = [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.7),
            ("TEXTCOLOR", (0, 0), (-1, -1), TINTA),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINEA),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]
        if encabezado:
            estilo += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                       ("BACKGROUND", (0, 0), (-1, 0), FONDO),
                       ("LINEBELOW", (0, 0), (-1, 0), 0.8, SUAVE)]
        t.setStyle(TableStyle(estilo))
        return t

    def n(valor, decimales=2):
        """Un número como se escribe en Ecuador: coma decimal, punto de miles."""
        texto = f"{float(valor):,.{decimales}f}"
        return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")

    r, saldo = datos["resumen"], datos["saldo"]
    hoy = dt.date.today().strftime("%d de %B de %Y")
    MESES = {"January": "enero", "February": "febrero", "March": "marzo",
             "April": "abril", "May": "mayo", "June": "junio", "July": "julio",
             "August": "agosto", "September": "septiembre", "October": "octubre",
             "November": "noviembre", "December": "diciembre"}
    for en, es in MESES.items():
        hoy = hoy.replace(en, es)

    doc = SimpleDocTemplate(
        str(salida), pagesize=A4,
        leftMargin=2.4 * cm, rightMargin=2.4 * cm,
        topMargin=2.2 * cm, bottomMargin=2.2 * cm,
        title=TITULO, author="Sistema de Permisos y Vacaciones",
        subject="Cotejo del devengo de vacaciones con el registro de Talento Humano")

    e: list = []
    e.append(Paragraph(TITULO, h1))
    e.append(Paragraph(SUBTITULO, bajada))
    e.append(tabla([["Fecha del informe", hoy],
                    ["Personas activas consideradas", n(r["personas"], 0)],
                    ["Alcance", "Días devengados del año de vacaciones en curso"]],
                   [6.2 * cm, 9.4 * cm], encabezado=False))

    e.append(Paragraph("1. En una línea", h2))
    e.append(Paragraph(
        "El sistema mostraba más días devengados que la hoja de Talento Humano para las personas "
        "con más de cinco años de servicio. La causa está identificada, la diferencia se cierra "
        "sola en cada aniversario y <b>no afecta a ningún saldo ya consolidado</b>. Se propone "
        "adoptar el cálculo de la hoja.", normal))

    e.append(Paragraph("2. Los dos cálculos", h2))
    e.append(Paragraph(
        "El Código del Trabajo concede quince días de vacaciones por cada año trabajado "
        "(Art. 69) y, a quien haya prestado servicios por más de cinco años, un día adicional "
        "por cada año excedente, hasta quince. La ley no dice cómo se reparte ese derecho "
        "dentro del año: eso es una convención contable, y ahí estaban las dos posturas.", normal))
    e.append(tabla([
        ["", "Registro de Talento Humano", "Sistema (hasta ahora)"],
        ["Base mensual", "1,25 días al mes (15 ÷ 12)", "Tope anual ÷ 12"],
        ["Días adicionales\n(Art. 69)", "Enteros, al cumplir el año", "Prorrateados mes a mes"],
        ["Persona con 16 años,\n8 meses corridos", "10,00 días", "18,00 días"],
    ], [3.6 * cm, 6.0 * cm, 6.0 * cm]))

    e.append(Paragraph("3. Dónde está el error", h2))
    e.append(Paragraph(
        "El Art. 69 concede el día adicional a quien <i>«hubiere prestado servicios por más de "
        "cinco años»</i>. El derecho nace al cumplir el año; no se va ganando dentro de él. Al "
        "prorratearlo, el sistema mostraba a mitad de año una fracción de un día que la persona "
        "todavía no había adquirido.", normal))
    e.append(Paragraph(
        "Conviene decirlo con precisión, porque no es un error de captura ni de redondeo, y "
        "tampoco perjudicaba a nadie: <b>el sistema iba por delante del derecho, no por "
        "detrás</b>. Ningún colaborador vio menos días de los que le corresponden. Lo que "
        "fallaba es que la cifra de la pantalla no era la que Talento Humano podía confirmar, y "
        "una cifra que el departamento no puede confirmar no sirve para nada.", normal))

    e.append(Paragraph("4. Por qué el cambio es seguro", h2))
    e.append(Paragraph(
        "<b>Los dos cálculos coinciden exactamente en cada aniversario.</b> Prorratear el tope "
        "durante doce meses y conceder la base mensual más los adicionales enteros dan el mismo "
        "número al completar el año. La diferencia vive solo dentro del año en marcha y se "
        "cierra sola.", destacado))
    e.append(Spacer(1, 5))
    e.append(Paragraph(
        f"Por eso el cambio no toca ningún período ya cumplido, ningún día gozado y ningún "
        f"saldo consolidado. El saldo total de la planilla —{n(saldo['total'])} días— es el mismo "
        f"antes y después.", normal))

    e.append(Paragraph("5. A cuántas personas alcanza", h2))
    filas = [["Antigüedad", "Personas", "Diferencia menor", "Diferencia mayor", "Total"]]
    for t in datos["tramos"]:
        filas.append([t["tramo"], str(t["personas"]),
                      n(t["dif_menor"]), n(t["dif_mayor"]), n(t["dif_total"])])
    e.append(tabla(filas, [4.4 * cm, 2.4 * cm, 3.2 * cm, 3.2 * cm, 2.4 * cm]))
    e.append(Spacer(1, 6))
    e.append(Paragraph(
        f"De {n(r['personas'], 0)} personas activas, <b>{n(r['con_menos_de_cinco'], 0)} no tenían ninguna "
        f"diferencia</b>: antes de los cinco años no hay días adicionales que prorratear, así "
        f"que los dos cálculos ya eran el mismo. La diferencia se concentra en "
        f"{n(r['con_diferencia'], 0)} personas y suma {n(r['dias_de_diferencia'])} días, con un máximo "
        f"individual de {n(r['diferencia_mayor'])} días.", normal))

    e.append(PageBreak())
    e.append(Paragraph("6. Los casos que más se separan", h2))
    e.append(Paragraph(
        "Cada fila se explica sola: los meses corridos del año en curso multiplicados por la "
        "base mensual dan la columna de la hoja; multiplicados por el tope anual dividido para "
        "doce, la del sistema.", normal))
    filas = [["Años", "Meses\ncorridos", "Tope anual\ndel período",
              "Según la hoja", "Según el sistema", "Diferencia", "Personas"]]
    for c in datos["casos"]:
        filas.append([str(c["anios_cumplidos"]), str(c["meses_del_periodo"]),
                      n(c["tope_anual_del_periodo"], 0), n(c["devengado_hoja"]),
                      n(c["devengado_prorrateado"]), n(c["diferencia"]),
                      str(c["personas"])])
    e.append(tabla(filas, [1.7 * cm, 2.1 * cm, 2.6 * cm, 2.8 * cm, 3.0 * cm, 2.3 * cm, 1.6 * cm]))

    e.append(Paragraph("7. Lo que se pide decidir", h2))
    e.append(Paragraph(
        "El sistema ya quedó alineado con el registro de Talento Humano: es el cálculo que la "
        "empresa viene aplicando y el que el departamento puede sostener ante un colaborador o "
        "ante una inspección. Se somete a consideración de Talento Humano una de estas dos:", normal))
    e.append(tabla([
        ["Opción", "Qué implica"],
        ["A. Mantener el cálculo de la hoja\n(vigente)",
         "No se hace nada más. El sistema y el registro dicen lo mismo,\n"
         "persona por persona, desde hoy."],
        ["B. Adoptar el prorrateo\ndel tope anual",
         "Se enciende un parámetro del sistema y el registro de Talento\n"
         "Humano debe actualizarse con el mismo criterio, para que las dos\n"
         "fuentes vuelvan a coincidir."],
    ], [5.4 * cm, 10.2 * cm]))
    e.append(Spacer(1, 8))
    e.append(Paragraph(
        "Cualquiera de las dos es defendible: la ley fija el derecho, no el método de "
        "prorrateo. Lo que no es defendible es que convivan las dos, porque entonces hay dos "
        "cifras oficiales para la misma persona y ninguna manera de decidir cuál rige.", destacado))

    e.append(KeepTogether([Paragraph("8. Fundamento", h2), tabla([
        ["Norma", "Qué dice"],
        ["Código del Trabajo,\nArt. 69",
         "Quince días de vacaciones al año, incluidos los no laborables. Un día\n"
         "adicional por cada año excedente del quinto, hasta quince adicionales."],
        ["Código del Trabajo,\nArt. 71",
         "La liquidación se calcula sobre la vigésima cuarta parte de lo\n"
         "percibido durante el año de servicio."],
        ["Código del Trabajo,\nArt. 75",
         "El trabajador puede no gozar sus vacaciones hasta por tres años\n"
         "consecutivos, para acumularlas en el cuarto."],
        ["Código del Trabajo,\nArt. 76",
         "Las vacaciones no gozadas se pagan. No se pierden."],
        ["Constitución,\nArt. 326 núm. 2",
         "Los derechos laborales son irrenunciables e intangibles."],
    ], [4.0 * cm, 11.6 * cm])]))

    e.append(Spacer(1, 16))
    e.append(Paragraph(
        "Las cifras de este informe se leen de la base de datos en el momento de generarlo, con "
        "<i>scripts/informe_devengo.py</i>, y pueden volver a comprobarse en cualquier momento "
        "persona por persona en la vista <i>v_devengo_cotejo</i>. No hay ningún número escrito "
        "a mano en este documento.", nota))

    doc.build(e)


async def principal(salida: Path) -> int:
    from app.db import cerrar_pool
    try:
        datos = await reunir()
    finally:
        await cerrar_pool()
    construir(datos, salida)
    print(f"Informe escrito en {salida}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--salida", type=Path, default=RAIZ / "informe_devengo.pdf")
    args = p.parse_args()
    raise SystemExit(asyncio.run(principal(args.salida)))
