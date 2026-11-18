"""Mapa de dependencias para depurar la base sin romper procesos.

    python scripts/informe_depuracion.py

Lo que hace falta antes de escribir un DELETE contra datos reales: qué se
lleva por delante cada borrado, qué lo bloquea y qué se recalcula solo.

Se lee del esquema tal como está hoy. Una lista escrita a mano se desactualiza
con la primera migración, y aquí equivocarse cuesta un expediente laboral.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

TITULO = "Depuración de la base de datos"
SUBTITULO = "Qué arrastra cada borrado, qué lo bloquea y qué se recalcula solo"


async def reunir() -> dict:
    from app.db import obtener_todos, obtener_uno

    relaciones = await obtener_todos("""
        select c.confrelid::regclass::text as padre,
               c.conrelid::regclass::text  as hija,
               a.attname                   as columna,
               c.confdeltype               as al_borrar
          from pg_constraint c
          join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
         where c.contype = 'f' and c.connamespace = 'public'::regnamespace
         order by 1, 2""")

    disparadores = await obtener_todos("""
        select c.relname as tabla, t.tgname as nombre, p.proname as funcion,
               case when t.tgtype::int & 2 > 0 then 'antes' else 'después' end as momento,
               (case when t.tgtype::int & 4  > 0 then 'insertar ' else '' end ||
                case when t.tgtype::int & 8  > 0 then 'borrar '   else '' end ||
                case when t.tgtype::int & 16 > 0 then 'actualizar' else '' end) as cuando
          from pg_trigger t
          join pg_class c on c.oid = t.tgrelid
          join pg_proc  p on p.oid = t.tgfoid
         where not t.tgisinternal and c.relnamespace = 'public'::regnamespace
         order by 1, 2""")

    generadas = await obtener_todos("""
        select table_name as tabla, column_name as columna, generation_expression as formula
          from information_schema.columns
         where table_schema = 'public' and is_generated = 'ALWAYS'
         order by 1, 2""")

    filas = {}
    tablas = await obtener_todos("""
        select c.relname as tabla from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind = 'r' order by 1""")
    for t in tablas:
        try:
            r = await obtener_uno(f'select count(*) as n from public."{t["tabla"]}"')
            filas[t["tabla"]] = int(r["n"])
        except Exception:                       # noqa: BLE001
            filas[t["tabla"]] = None

    return {"relaciones": relaciones, "disparadores": disparadores,
            "generadas": generadas, "filas": filas}


def construir(datos: dict, salida: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    TINTA, SUAVE = colors.HexColor("#0f172a"), colors.HexColor("#475569")
    LINEA, FONDO = colors.HexColor("#cbd5e1"), colors.HexColor("#f1f5f9")
    ROJO, AMBAR = colors.HexColor("#be123c"), colors.HexColor("#b45309")

    hojas = getSampleStyleSheet()
    normal = ParagraphStyle("c", parent=hojas["Normal"], fontName="Helvetica",
                            fontSize=9.6, leading=14, alignment=TA_JUSTIFY,
                            textColor=TINTA, spaceAfter=6)
    h1 = ParagraphStyle("h1", parent=normal, fontName="Helvetica-Bold", fontSize=17,
                        leading=21, alignment=0, spaceAfter=3)
    bajada = ParagraphStyle("b", parent=normal, fontSize=10.5, leading=15,
                            textColor=SUAVE, alignment=0, spaceAfter=14)
    h2 = ParagraphStyle("h2", parent=normal, fontName="Helvetica-Bold", fontSize=12,
                        leading=16, alignment=0, spaceBefore=13, spaceAfter=4)
    celda = ParagraphStyle("ce", parent=normal, fontSize=8.3, leading=11,
                           alignment=0, spaceAfter=0)
    mono = ParagraphStyle("mo", parent=celda, fontName="Courier", fontSize=7.8)
    alarma = ParagraphStyle("al", parent=normal, fontName="Helvetica-Bold",
                            fontSize=10.5, leading=15, alignment=0, textColor=ROJO)
    nota = ParagraphStyle("no", parent=normal, fontSize=8.3, leading=11.5,
                          textColor=SUAVE)
    fuerte = ParagraphStyle("fu", parent=normal, fontName="Helvetica-Bold",
                            fontSize=10, leading=14.5, alignment=0)

    def n(v):
        if v is None:
            return "—"
        return f"{v:,}".replace(",", ".")

    def tabla(filas, anchos, encabezado=True):
        t = Table(filas, colWidths=anchos, hAlign="LEFT", repeatRows=1 if encabezado else 0)
        estilo = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                  ("FONTSIZE", (0, 0), (-1, -1), 8.3),
                  ("TEXTCOLOR", (0, 0), (-1, -1), TINTA),
                  ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINEA),
                  ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("TOPPADDING", (0, 0), (-1, -1), 4),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                  ("LEFTPADDING", (0, 0), (-1, -1), 5)]
        if encabezado:
            estilo += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                       ("BACKGROUND", (0, 0), (-1, 0), FONDO),
                       ("LINEBELOW", (0, 0), (-1, 0), 0.8, SUAVE)]
        t.setStyle(TableStyle(estilo))
        return t

    ACCION = {"c": "SE BORRA EN CASCADA", "n": "se queda, pierde la referencia",
              "d": "se queda, toma el valor por defecto",
              "a": "BLOQUEA el borrado", "r": "BLOQUEA el borrado"}

    rel = datos["relaciones"]
    cascadas = {}
    for r in rel:
        if r["al_borrar"] == "c":
            cascadas.setdefault(r["padre"], []).append(r["hija"])

    hoy = dt.date.today()
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    doc = SimpleDocTemplate(str(salida), pagesize=A4,
                            leftMargin=2.1 * cm, rightMargin=2.1 * cm,
                            topMargin=2.0 * cm, bottomMargin=2.0 * cm,
                            title=TITULO, author="ITSANET", subject=SUBTITULO)

    e: list = []
    e.append(Paragraph(TITULO, h1))
    e.append(Paragraph(SUBTITULO, bajada))
    e.append(Paragraph(
        f"Generado el {hoy.day} de {MESES[hoy.month - 1]} de {hoy.year} leyendo el esquema "
        "tal como está. Acompaña a los archivos de <i>supabase/depuracion/</i>.", nota))

    e.append(Paragraph("1. Lo primero, porque cambia todo lo demás", h2))
    e.append(Paragraph(
        "Conectarse como <b>postgres</b> apaga las tres protecciones del sistema.", alarma))
    e.append(Paragraph(
        "Las bitácoras dejan de ser inmutables, la restricción que impide cambiar el rol o "
        "el saldo de otra persona deja de aplicar, y la seguridad por fila no filtra nada. "
        "Está hecho así a propósito —el mantenimiento tiene que poder trabajar—, pero "
        "significa que en DBeaver, con el usuario administrador, la base no lo va a detener "
        "ante nada. Ni ante un DELETE sin WHERE.", normal))
    e.append(Paragraph(
        "Desactive el auto-commit antes de empezar. Con auto-commit encendido cada sentencia "
        "se guarda sola y <i>rollback</i> ya no sirve.", normal))

    e.append(Paragraph("2. El borrado más peligroso de la base", h2))
    hijas = sorted(cascadas.get("users", []))
    # Y lo que a su vez arrastran esas tablas: el borrado no se detiene en el
    # primer nivel, y decir solo el primero se queda corto.
    segundo = sorted({h for t in hijas for h in cascadas.get(t, [])} - set(hijas))
    e.append(Paragraph(
        f"Borrar una fila de <b>users</b> arrastra en cascada {len(hijas)} tablas"
        + (f", y a través de ellas {len(segundo)} más" if segundo else "")
        + ". Sin preguntar y sin dejar rastro:", normal))
    e.append(tabla([[Paragraph(", ".join(hijas), celda)]], [16.6 * cm], encabezado=False))
    if segundo:
        e.append(Spacer(1, 3))
        e.append(Paragraph(
            f"Y con ellas: {', '.join(segundo)}.", nota))
    e.append(Spacer(1, 4))
    e.append(Paragraph(
        "Es el expediente laboral completo: solicitudes, períodos de vacaciones, historial, "
        "firmas, familiares, conversaciones y los consentimientos de protección de datos, "
        "que es justo lo que la LOPDP obliga a poder demostrar. Para dar de baja a alguien "
        "se desactiva:", normal))
    e.append(tabla([[Paragraph(
        "update public.users set activo = false, fecha_salida = current_date "
        "where cedula = '0000000000';", mono)]], [16.6 * cm], encabezado=False))

    e.append(PageBreak())
    e.append(Paragraph("3. Qué arrastra cada borrado", h2))
    e.append(Paragraph(
        "Ordenado por gravedad. Las cascadas primero: son las que actúan en silencio.", normal))

    orden = {"c": 0, "a": 1, "r": 1, "n": 2, "d": 3}
    filas = [["Si borra de", "Se afecta", "Por la columna", "Consecuencia"]]
    for r in sorted(rel, key=lambda x: (orden.get(x["al_borrar"], 9), x["padre"], x["hija"])):
        color = (ROJO if r["al_borrar"] == "c"
                 else AMBAR if r["al_borrar"] in ("a", "r") else SUAVE)
        filas.append([
            Paragraph(f"<b>{r['padre']}</b>", celda),
            Paragraph(r["hija"], celda),
            Paragraph(r["columna"], mono),
            Paragraph(f"<font color='#{color.hexval()[2:]}'>{ACCION[r['al_borrar']]}</font>", celda),
        ])
    e.append(tabla(filas, [3.6 * cm, 4.4 * cm, 3.6 * cm, 5.0 * cm]))

    e.append(PageBreak())
    e.append(Paragraph("4. Lo que el sistema recalcula solo", h2))
    e.append(Paragraph(
        "Editar a mano una columna que un disparador recalcula es perder el trabajo sin "
        "enterarse: el número aguanta hasta el siguiente movimiento y vuelve al anterior.", normal))

    filas = [["Tabla", "Cuándo actúa", "Qué hace"]]
    EXPLICA = {
        "tg_vac_periods_sync": "Recalcula users.dias_vacaciones sumando los períodos. "
                               "Por esto el saldo NO se edita a mano.",
        "cerrar_fines_semana_si_completo": "Da por cumplidos los fines de semana de un "
                                           "período gozado por completo.",
        "tg_log_inmutable": "Impide modificar o borrar la bitácora. No aplica si entró "
                            "como postgres.",
        "tg_users_proteger_campos": "Impide que alguien que no sea Talento Humano cambie "
                                    "rol, cédula, saldo o fecha de ingreso.",
        "tg_users_region": "Deduce users.region de users.ciudad.",
        "tg_requests_folio": "Asigna el número de solicitud.",
        "tg_requests_region": "Asigna la región que atiende la solicitud.",
        "tg_requests_ruta_aprobacion": "Decide si pasa por jefe, por Talento Humano o por ambos.",
        "tg_requests_notificar": "Genera los avisos de cada cambio de estado.",
        "tg_requests_audit": "Anota el movimiento en la bitácora.",
        "tg_mensajes_tocar": "Reabre la conversación cuando llega un mensaje.",
    }
    # Los que solo tocan una marca de tiempo no se listan: son ocho filas
    # diciendo lo mismo y entierran las tres que de verdad hay que conocer
    # antes de editar algo a mano.
    for d in datos["disparadores"]:
        explicacion = EXPLICA.get(d["funcion"])
        if not explicacion:
            continue
        filas.append([Paragraph(f"<b>{d['tabla']}</b>", celda),
                      Paragraph(f"{d['momento']} de {d['cuando'].strip()}", celda),
                      Paragraph(explicacion, celda)])
    # Lo que impide o recalcula va arriba; lo que solo completa un dato, abajo.
    PESO = {"tg_vac_periods_sync": 0, "tg_log_inmutable": 0,
            "tg_users_proteger_campos": 0, "cerrar_fines_semana_si_completo": 1,
            "tg_users_region": 1}
    filas[1:] = sorted(filas[1:], key=lambda f: f[0].text)
    e.append(tabla(filas, [3.4 * cm, 3.6 * cm, 9.6 * cm]))

    if datos["generadas"]:
        e.append(Spacer(1, 8))
        e.append(Paragraph("Columnas calculadas (no admiten UPDATE)", fuerte))
        e.append(tabla([["Columna", "Fórmula"]] +
                       [[Paragraph(f"{g['tabla']}.{g['columna']}", mono),
                         Paragraph(g["formula"], mono)] for g in datos["generadas"]],
                       [5.6 * cm, 11.0 * cm]))

    e.append(Paragraph("5. Después de tocar datos", h2))
    e.append(tabla([
        ["Si cambió", "Ejecute"],
        [Paragraph("Un saldo, un período o días consumidos", celda),
         Paragraph("select public.recalcular_saldos();", mono)],
        [Paragraph("Una fecha de ingreso", celda),
         Paragraph("select public.generar_periodos_vacaciones('UUID');<br/>"
                   "select public.recalcular_saldos('UUID');", mono)],
        [Paragraph("El saldo real de una persona", celda),
         Paragraph("select public.cargar_saldo_inicial('UUID', 8.75, 0);", mono)],
        [Paragraph("Nombres, para volver a cargar el historial", celda),
         Paragraph("python scripts\\cargar_historial.py ARCHIVO.xlsx --aplicar", mono)],
    ], [6.2 * cm, 10.4 * cm]))

    e.append(Paragraph("6. Cuánto hay hoy en cada tabla", h2))
    conteos = sorted(datos["filas"].items(), key=lambda x: -(x[1] or 0))
    columnas = [conteos[i::3] for i in range(3)]
    largo = max(len(c) for c in columnas)
    filas = [["Tabla", "Filas", "Tabla", "Filas", "Tabla", "Filas"]]
    for i in range(largo):
        fila = []
        for col in columnas:
            if i < len(col):
                fila += [Paragraph(col[i][0], celda), Paragraph(n(col[i][1]), celda)]
            else:
                fila += ["", ""]
        filas.append(fila)
    e.append(tabla(filas, [3.9 * cm, 1.6 * cm, 3.9 * cm, 1.6 * cm, 3.9 * cm, 1.7 * cm]))

    e.append(Spacer(1, 12))
    e.append(Paragraph(
        "Las tablas y las relaciones se leen del esquema al generar este documento, con "
        "<i>scripts/informe_depuracion.py</i>. Una lista escrita a mano se desactualiza con "
        "la primera migración, y aquí equivocarse cuesta un expediente laboral.", nota))

    doc.build(e)


async def principal(salida: Path) -> int:
    from app.db import cerrar_pool
    try:
        datos = await reunir()
    finally:
        await cerrar_pool()
    construir(datos, salida)
    print(f"Documento escrito en {salida}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--salida", type=Path, default=RAIZ / "depuracion_base_datos.pdf")
    args = _cli.analizar(p)
    raise SystemExit(asyncio.run(principal(args.salida)))
