"""Documento de la estructura de la base de datos, para presentarla.

    python scripts/informe_base_datos.py
    python scripts/informe_base_datos.py --salida ruta.pdf

No es un volcado de columnas: eso lo da cualquier herramienta y no explica
nada. Lo que hace falta para presentar un sistema es por qué está armado así,
y eso no se lee del catálogo.

Las cifras —cuántas tablas, cuántas filas, qué políticas de acceso hay
puestas— se leen de la base cada vez que se genera. Un documento con números
a mano envejece el mismo día.
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

TITULO = "Estructura de la base de datos"
SUBTITULO = "Sistema de Permisos, Vacaciones y Control de Garita"

# Los grupos, en el orden en que se explican. Cada uno responde a una
# pregunta del negocio, no a una afinidad técnica: quien presenta esto tiene
# que poder decir para qué sirve cada bloque sin hablar de bases de datos.
GRUPOS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Las personas",
     "Quién trabaja aquí, quién es su jefe y qué datos suyos guarda el sistema. "
     "La cédula identifica a cada persona y nunca se repite.",
     ("users", "campos_ficha", "cambios_ficha", "family_members",
      "emergency_contacts", "altas_pendientes", "confirmaciones_correo")),

    ("Las ausencias",
     "Toda solicitud de permiso o vacaciones, con su recorrido completo: quién "
     "la pidió, quién la autorizó, cuándo y con qué respaldo. Nada se borra; lo "
     "que se anula queda anulado y a la vista.",
     ("requests", "permission_types", "permission_categories",
      "request_attachments", "request_adjustments", "signatures",
      "request_signatures")),

    ("Las vacaciones",
     "El saldo no es un número suelto: sale de sumar lo que queda en cada año de "
     "servicio. Así se puede responder de dónde viene cada día y desde cuándo se "
     "arrastra.",
     ("vacation_periods", "vacation_movements", "vacaciones_historicas",
      "antiguedad_referencia", "feriados")),

    ("El control de acceso",
     "Lo que la garita presenció: quién salió, a qué hora volvió y quién entró de "
     "visita. Es la parte que sustenta un descuento o una sanción, así que solo "
     "se escribe y no se corrige.",
     ("access_logs", "visitors", "personal_temporal", "jornadas_temporales")),

    ("La comunicación",
     "Consultas a Talento Humano y avisos del sistema. Existen para que una duda "
     "no acabe en el teléfono personal de alguien, fuera de todo registro.",
     ("conversaciones", "mensajes", "notifications")),

    ("Las reglas",
     "Lo que la empresa decide y puede cambiar sin tocar el programa: parámetros, "
     "lineamientos, qué se muestra en la pantalla principal y el texto de cada "
     "norma que el sistema aplica.",
     ("app_config", "legal_references", "lineamientos_solicitud",
      "panel_bloques", "regiones", "ciudades_region")),

    ("La protección de datos",
     "Lo que la LOPDP exige poder demostrar: quién consintió qué, quién ejerció "
     "sus derechos y quién miró cada cosa.",
     ("data_consents", "data_subject_requests", "audit_logs", "auth_otp")),
]


async def reunir() -> dict:
    from app.db import obtener_todos, obtener_uno

    tablas = await obtener_todos("""
        select c.relname as tabla,
               obj_description(c.oid) as descripcion,
               c.relrowsecurity as rls,
               (select count(*) from pg_attribute a
                 where a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped) as columnas,
               (select count(*) from pg_policy p where p.polrelid = c.oid) as politicas
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind = 'r'
         order by c.relname""")

    filas = {}
    for t in tablas:
        try:
            r = await obtener_uno(f'select count(*) as n from public."{t["tabla"]}"')
            filas[t["tabla"]] = int(r["n"])
        except Exception:                      # noqa: BLE001
            filas[t["tabla"]] = None

    resumen = await obtener_uno("""
        select (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'r')                    as tablas,
               (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'v')                    as vistas,
               (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                 where n.nspname = 'public')                                        as funciones,
               (select count(*) from pg_trigger where not tgisinternal)              as disparadores,
               (select count(*) from pg_policy)                                      as politicas,
               (select count(*) from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where n.nspname = 'public' and t.typtype = 'e')                    as enumerados,
               (select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
                 where n.nspname = 'public' and c.relkind = 'i')                    as indices""")

    claves = await obtener_uno("""
        select count(*) filter (where contype = 'f') as foraneas,
               count(*) filter (where contype = 'c') as comprobaciones,
               count(*) filter (where contype = 'u') as unicas
          from pg_constraint c
          join pg_namespace n on n.oid = c.connamespace
         where n.nspname = 'public'""")

    sin_rls = [t["tabla"] for t in tablas if not t["rls"]]
    return {"tablas": tablas, "filas": filas, "resumen": resumen,
            "claves": claves, "sin_rls": sin_rls}


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
                            fontSize=9.6, leading=14, alignment=TA_JUSTIFY,
                            textColor=TINTA, spaceAfter=6)
    h1 = ParagraphStyle("h1", parent=normal, fontName="Helvetica-Bold", fontSize=17,
                        leading=21, alignment=0, spaceAfter=3)
    bajada = ParagraphStyle("bajada", parent=normal, fontSize=10.5, leading=15,
                            textColor=SUAVE, alignment=0, spaceAfter=14)
    h2 = ParagraphStyle("h2", parent=normal, fontName="Helvetica-Bold", fontSize=12,
                        leading=16, alignment=0, spaceBefore=13, spaceAfter=4)
    celda = ParagraphStyle("celda", parent=normal, fontSize=8.3, leading=11,
                           alignment=0, spaceAfter=0)
    nota = ParagraphStyle("nota", parent=normal, fontSize=8.3, leading=11.5,
                          textColor=SUAVE)
    fuerte = ParagraphStyle("fuerte", parent=normal, fontName="Helvetica-Bold",
                            fontSize=10, leading=14.5, alignment=0)

    def n(valor, decimales=0):
        if valor is None:
            return "—"
        texto = f"{float(valor):,.{decimales}f}"
        return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")

    def tabla(filas, anchos, encabezado=True, tamano=8.3):
        t = Table(filas, colWidths=anchos, hAlign="LEFT", repeatRows=1 if encabezado else 0)
        estilo = [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), tamano),
            ("TEXTCOLOR", (0, 0), (-1, -1), TINTA),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINEA),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]
        if encabezado:
            estilo += [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                       ("BACKGROUND", (0, 0), (-1, 0), FONDO),
                       ("LINEBELOW", (0, 0), (-1, 0), 0.8, SUAVE)]
        t.setStyle(TableStyle(estilo))
        return t

    r, c = datos["resumen"], datos["claves"]
    por_nombre = {t["tabla"]: t for t in datos["tablas"]}
    hoy = dt.date.today()
    MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    fecha_larga = f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}"

    doc = SimpleDocTemplate(
        str(salida), pagesize=A4,
        leftMargin=2.1 * cm, rightMargin=2.1 * cm,
        topMargin=2.0 * cm, bottomMargin=2.0 * cm,
        title=TITULO, author="ITSANET", subject=SUBTITULO)

    e: list = []
    e.append(Paragraph(TITULO, h1))
    e.append(Paragraph(SUBTITULO, bajada))

    e.append(tabla([
        ["Motor", "PostgreSQL (Supabase)"],
        ["Tablas", n(r["tablas"])],
        ["Vistas", n(r["vistas"])],
        ["Funciones y disparadores", f"{n(r['funciones'])} funciones · {n(r['disparadores'])} disparadores"],
        ["Reglas de integridad", f"{n(c['foraneas'])} claves foráneas · "
                                 f"{n(c['comprobaciones'])} comprobaciones · {n(c['unicas'])} únicas"],
        ["Políticas de acceso por fila", n(r["politicas"])],
        ["Fecha del documento", fecha_larga],
    ], [6.0 * cm, 10.6 * cm], encabezado=False))

    e.append(Paragraph("1. Cómo está organizada", h2))
    e.append(Paragraph(
        "La base no está dividida por afinidad técnica sino por preguntas del negocio. "
        "Cada grupo de tablas responde una, y esa es la forma de explicarla sin hablar "
        "de bases de datos.", normal))

    filas = [["Grupo", "Responde a", "Tablas"]]
    for titulo, proposito, tablas_grupo in GRUPOS:
        presentes = [t for t in tablas_grupo if t in por_nombre]
        filas.append([Paragraph(f"<b>{titulo}</b>", celda),
                      Paragraph(proposito, celda),
                      Paragraph(str(len(presentes)), celda)])
    e.append(tabla(filas, [3.4 * cm, 11.2 * cm, 2.0 * cm]))

    e.append(Paragraph("2. Cuatro decisiones que explican el resto", h2))
    for titulo, texto in [
        ("El saldo de vacaciones no se guarda como un número",
         "Se guarda un registro por cada año de servicio —<i>vacation_periods</i>— con lo "
         "asignado y lo consumido de ese año. El saldo es la suma. Cuesta más, y a cambio "
         "el sistema puede responder de qué año viene cada día y desde cuándo se arrastra, "
         "que es lo que pregunta un colaborador cuando no está de acuerdo."),
        ("Lo que venía de la hoja no se mezcló con lo que se tramita aquí",
         "Las vacaciones que Talento Humano llevaba antes del sistema están en su propia "
         "tabla, <i>vacaciones_historicas</i>. No tienen folio ni autorización porque nunca "
         "las tuvieron. Meterlas entre las solicitudes habría inventado un trámite que no "
         "ocurrió, y en pantalla aparecen marcadas por su origen."),
        ("Nada se borra",
         "Una solicitud anulada queda anulada, no desaparece. Los ajustes de Talento Humano "
         "se insertan, nunca reemplazan. Desactivar a una persona cambia un indicador; su "
         "expediente permanece. Un dato que se esfuma es un dato que nadie puede auditar."),
        ("Quién ve qué lo decide la base, no la pantalla",
         "Las políticas de acceso por fila viven en PostgreSQL. Un jefe ve a su equipo y "
         "Talento Humano ve a todos porque la base lo impone; esconder un botón no protege "
         "nada frente a quien sepa escribir una dirección."),
    ]:
        e.append(KeepTogether([Paragraph(titulo, fuerte),
                               Paragraph(texto, normal), Spacer(1, 3)]))

    e.append(PageBreak())
    e.append(Paragraph("3. Las tablas, grupo por grupo", h2))
    e.append(Paragraph(
        "«Filas» es lo que hay hoy en esta base. «RLS» indica si la tabla tiene activada "
        "la seguridad por fila de PostgreSQL, y entre paréntesis cuántas políticas la "
        "gobiernan.", normal))

    for titulo, proposito, tablas_grupo in GRUPOS:
        presentes = [t for t in tablas_grupo if t in por_nombre]
        if not presentes:
            continue
        filas = [["Tabla", "Qué guarda", "Col.", "Filas", "RLS"]]
        for nombre in presentes:
            t = por_nombre[nombre]
            descripcion = (t["descripcion"] or "").strip() or "—"
            filas.append([
                Paragraph(f"<b>{nombre}</b>", celda),
                Paragraph(descripcion, celda),
                Paragraph(str(t["columnas"]), celda),
                Paragraph(n(datos["filas"].get(nombre)), celda),
                Paragraph("Sí" if t["rls"] else "No", celda)
                if not t["politicas"] else
                Paragraph(f"Sí ({t['politicas']})", celda),
            ])
        e.append(KeepTogether([
            Paragraph(titulo, fuerte), Paragraph(proposito, nota), Spacer(1, 3)]))
        e.append(tabla(filas, [3.6 * cm, 9.2 * cm, 1.3 * cm, 1.5 * cm, 1.0 * cm]))
        e.append(Spacer(1, 7))

    sueltas = [t["tabla"] for t in datos["tablas"]
               if not any(t["tabla"] in g[2] for g in GRUPOS)]
    if sueltas:
        e.append(Paragraph("Otras tablas", fuerte))
        e.append(Paragraph(", ".join(sueltas), normal))

    e.append(PageBreak())
    e.append(Paragraph("4. Protección de datos", h2))
    e.append(Paragraph(
        "El sistema trata datos personales de trabajadores en Ecuador, así que le aplica la "
        "Ley Orgánica de Protección de Datos Personales. Lo que la base hace al respecto:", normal))
    e.append(tabla([
        ["Exigencia", "Cómo se cumple"],
        [Paragraph("Acceso solo a lo que corresponde<br/>(Art. 10)", celda),
         Paragraph(f"Seguridad por fila en PostgreSQL con {n(r['politicas'])} políticas. "
                   "Un compañero no lee el expediente de otro, ni escribiendo la dirección "
                   "a mano. Un jefe alcanza a su equipo; Talento Humano, a la planilla.", celda)],
        [Paragraph("Consentimiento informado<br/>(Art. 7)", celda),
         Paragraph("<i>data_consents</i> guarda la versión de la política, la finalidad, "
                   "la fecha y la dirección desde la que se otorgó.", celda)],
        [Paragraph("Derechos del titular<br/>(Art. 12 a 16)", celda),
         Paragraph("<i>data_subject_requests</i> registra cada solicitud de acceso, "
                   "rectificación o eliminación, con su plazo legal de quince días.", celda)],
        [Paragraph("Trazabilidad", celda),
         Paragraph("<i>audit_logs</i> anota quién hizo qué, desde dónde y cuándo. "
                   "Incluye las descargas de informes: esos archivos salen del sistema.", celda)],
        [Paragraph("Datos sensibles", celda),
         Paragraph("El motivo de un permiso médico no aparece en el calendario del equipo: "
                   "ahí solo consta que la persona falta. La salud es dato sensible y se "
                   "queda en la solicitud, que ve quien la autoriza.", celda)],
    ], [4.2 * cm, 12.4 * cm]))

    if datos["sin_rls"]:
        e.append(Spacer(1, 6))
        e.append(Paragraph(
            f"Tablas sin seguridad por fila activada: {', '.join(datos['sin_rls'])}. "
            "Conviene revisar si alguna guarda datos personales.", nota))

    e.append(Paragraph("5. Fundamento de las reglas de vacaciones", h2))
    e.append(tabla([
        ["Norma", "Qué impone al sistema"],
        [Paragraph("Código del Trabajo, Art. 69", celda),
         Paragraph("Quince días al año, incluidos los no laborables, y un día adicional por "
                   "cada año pasado el quinto, hasta quince.", celda)],
        [Paragraph("Código del Trabajo, Art. 71", celda),
         Paragraph("La liquidación se calcula sobre la vigésima cuarta parte de lo percibido "
                   "en el año.", celda)],
        [Paragraph("Código del Trabajo, Art. 75", celda),
         Paragraph("Se pueden acumular hasta tres años para gozarlas en el cuarto.", celda)],
        [Paragraph("Código del Trabajo, Art. 76", celda),
         Paragraph("Las vacaciones no gozadas se pagan. El sistema no extingue días de nadie.", celda)],
        [Paragraph("Constitución, Art. 326 núm. 2", celda),
         Paragraph("Los derechos laborales son irrenunciables. Ninguna pantalla ofrece "
                   "renunciar a días.", celda)],
    ], [4.2 * cm, 12.4 * cm]))

    e.append(Spacer(1, 14))
    e.append(Paragraph(
        "Las cifras de este documento se leen de la base en el momento de generarlo, con "
        "<i>scripts/informe_base_datos.py</i>. No hay ningún número escrito a mano.", nota))

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
    p.add_argument("--salida", type=Path, default=RAIZ / "estructura_base_datos.pdf")
    args = _cli.analizar(p)
    raise SystemExit(asyncio.run(principal(args.salida)))
