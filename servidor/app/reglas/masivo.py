"""Actualización masiva de fichas por Excel, sin tocar la base a mano.

    1. Talento Humano descarga la plantilla con los datos ACTUALES de las
       personas que elija (todas, un área, una sede).
    2. Corrige en Excel lo que haga falta.
    3. La sube: el sistema la compara con lo que hay y muestra, persona por
       persona y campo por campo, qué cambiaría y qué tiene errores. Nada
       cambia todavía.
    4. Si está bien, la aplica con un motivo. Queda registrada con folio
       (CM-AAAA-NNNN), quién la subió, quién la aplicó, la huella del archivo
       y el detalle de cada cambio.

Una celda vacía significa «sin cambio», no «borrar»: así una columna que no
interesa se puede dejar en blanco sin riesgo.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import unicodedata
from typing import Any

from ..db import ejecutar, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio
from . import catalogo

CONTRATOS = {"indefinido": "indefinido", "eventual": "eventual", "ocasional": "ocasional",
             "temporada": "temporada", "de temporada": "temporada", "obra cierta": "obra_cierta",
             "por obra cierta": "obra_cierta", "obra_cierta": "obra_cierta", "prueba": "prueba",
             "a prueba": "prueba", "aprendizaje": "aprendizaje", "de aprendizaje": "aprendizaje",
             "pasantia": "pasantia"}

# (campo en users, encabezado de la plantilla, ancho de columna)
COLUMNAS = [
    ("cedula", "Cédula", 13), ("nombre", "Nombre (referencia, no se cambia aquí)", 34),
    ("cargo", "Cargo", 30), ("departamento", "Área", 24), ("jefe_cedula", "Cédula del jefe", 15),
    ("ciudad", "Ciudad de trabajo", 18), ("bodega", "Bodega", 16), ("centro_costo", "Centro de costo", 16),
    ("cliente", "Cliente", 16), ("tipo_contrato", "Tipo de contrato", 16),
    ("contrato_fin", "Fin del contrato (dd/mm/aaaa)", 18),
]
EDITABLES = [c for c, _, _ in COLUMNAS if c not in ("cedula", "nombre")]
ETIQUETA = {c: e.split(" (")[0] for c, e, _ in COLUMNAS}


def _plano(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


ENCABEZADOS = {_plano(e): c for c, e, _ in COLUMNAS}
ENCABEZADOS.update({_plano(e.split(" (")[0]): c for c, e, _ in COLUMNAS})


def _cedula(valor: Any) -> str:
    """Excel convierte «0912345678» en 912345678: se repone el cero."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    t = re.sub(r"\D", "", str(valor))
    return t.zfill(10) if 0 < len(t) < 10 else t


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dt.datetime, dt.date)):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return " ".join(str(valor).split())


def _fecha(valor: Any) -> dt.date | None:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    t = _texto(valor)
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(t, formato).date()
        except ValueError:
            pass
    raise ValueError(t)


# --------------------------------------------------------------- plantilla
async def plantilla(area: str | None, sede: str | None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    condiciones, params = ["u.activo"], []
    if area:
        condiciones.append("TRIM(u.departamento) = %s")
        params.append(area)
    if sede:
        condiciones.append("COALESCE(u.region, 'sierra') = %s")
        params.append(sede)
    filas = await obtener_todos(
        f"""SELECT u.cedula, u.nombre, u.cargo, u.departamento, j.cedula AS jefe_cedula, u.ciudad,
                   u.bodega, u.centro_costo, u.cliente, u.tipo_contrato, u.contrato_fin
              FROM users u LEFT JOIN users j ON j.id = u.jefe_id
             WHERE {' AND '.join(condiciones)} ORDER BY u.departamento, u.nombre""", tuple(params))
    elegir = await catalogo.para_elegir()

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Personas"
    hoja.append([e for _, e, _ in COLUMNAS])
    azul = PatternFill("solid", fgColor="1C58D7")
    gris = PatternFill("solid", fgColor="E6E6E6")
    for i, (campo, _, ancho) in enumerate(COLUMNAS, start=1):
        celda = hoja.cell(row=1, column=i)
        celda.font = Font(bold=True, color="FFFFFF" if campo in EDITABLES else "333434")
        celda.fill = azul if campo in EDITABLES else gris
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.row_dimensions[1].height = 32
    for f in filas:
        hoja.append([f["cedula"], f["nombre"], f["cargo"], f["departamento"], f["jefe_cedula"],
                     f["ciudad"], f["bodega"], f["centro_costo"], f["cliente"], f["tipo_contrato"],
                     f["contrato_fin"].strftime("%d/%m/%Y") if f["contrato_fin"] else None])
    for fila in hoja.iter_rows(min_row=2, max_col=2):
        for celda in fila:
            celda.number_format = "@"          # la cédula como texto: conserva el cero
            celda.fill = PatternFill("solid", fgColor="F7F7F7")
    hoja.freeze_panes = "C2"

    # Hoja de listas: los valores válidos de cargo, área y contrato, con
    # validación en las columnas para elegir de una lista desplegable.
    listas = libro.create_sheet("Listas")
    listas.append(["Áreas", "Cargos", "Tipo de contrato"])
    areas = [a["nombre"] for a in elegir["areas"]]
    cargos = sorted({c["nombre"] for c in elegir["cargos"]})
    contratos = ["indefinido", "eventual", "ocasional", "temporada", "obra_cierta", "prueba",
                 "aprendizaje", "pasantia"]
    for i in range(max(len(areas), len(cargos), len(contratos))):
        listas.append([areas[i] if i < len(areas) else None, cargos[i] if i < len(cargos) else None,
                       contratos[i] if i < len(contratos) else None])
    ultima = max(len(filas) + 200, 500)
    for columna, rango in (("D", f"Listas!$A$2:$A${len(areas) + 1}"),
                           ("C", f"Listas!$B$2:$B${len(cargos) + 1}"),
                           ("J", f"Listas!$C$2:$C${len(contratos) + 1}")):
        if rango.endswith("$1"):
            continue
        v = DataValidation(type="list", formula1=rango, allow_blank=True, showErrorMessage=False)
        v.add(f"{columna}2:{columna}{ultima}")
        hoja.add_data_validation(v)

    leeme = libro.create_sheet("Cómo usarla")
    for linea in [
        "Actualización masiva de fichas · ITSANET",
        "",
        "1. Corrija en la hoja «Personas» las columnas en azul. Las grises son de referencia.",
        "2. Una celda vacía significa «sin cambio». No se borra nada desde aquí.",
        "3. Cargo, área y tipo de contrato se eligen de la lista (hoja «Listas»). Un cargo o un",
        "   área nuevos se agregan al catálogo al aplicar.",
        "4. «Cédula del jefe»: la de una persona activa; no puede ser la misma persona.",
        "5. Cambiar la «Ciudad de trabajo» puede cambiar la sede de Talento Humano que la atiende.",
        "6. Suba el archivo en Administración › Actualización masiva: verá qué cambiaría antes de aplicar.",
        "",
        "Contiene datos personales (LOPDP). Guárdela solo en equipos de la empresa.",
    ]:
        leeme.append([linea])
    leeme["A1"].font = Font(bold=True, size=14, color="1C58D7")
    leeme.column_dimensions["A"].width = 100

    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


# ----------------------------------------------------------------- revisar
def _leer_crudas(nombre: str, contenido: bytes, hojas: tuple[str, ...] = ("Personas",)) -> list[list]:
    """Las filas tal cual. Acepta .xlsx (la primera hoja de `hojas` que
    exista, o la primera del libro) y .csv (; o ,)."""
    if nombre.lower().endswith(".csv"):
        texto = contenido.decode("utf-8-sig", errors="replace")
        separador = ";" if texto.count(";") >= texto.count(",") else ","
        crudas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    else:
        from openpyxl import load_workbook
        try:
            libro = load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001
            raise ReglaDeNegocio("No se pudo leer el archivo. Use la plantilla en Excel (.xlsx).") from exc
        hoja = next((libro[h] for h in hojas if h in libro.sheetnames), libro.worksheets[0])
        crudas = [list(f) for f in hoja.iter_rows(values_only=True)]
    if not crudas:
        raise ReglaDeNegocio("El archivo está vacío.")
    return crudas


def _leer(nombre: str, contenido: bytes) -> list[dict[str, Any]]:
    """Filas del archivo como {campo: valor}."""
    crudas = _leer_crudas(nombre, contenido)
    columnas = [ENCABEZADOS.get(_plano(c)) for c in crudas[0]]
    if "cedula" not in columnas:
        raise ReglaDeNegocio("No se encontró la columna «Cédula». Use la plantilla descargada.")
    filas = []
    for n, cruda in enumerate(crudas[1:], start=2):
        fila = {c: v for c, v in zip(columnas, cruda) if c}
        if any(v not in (None, "") for v in fila.values()):
            filas.append({"_fila": n, **fila})
    if len(filas) > 3000:
        raise ReglaDeNegocio("Máximo 3.000 filas por archivo.")
    return filas


async def revisar(nombre: str, contenido: bytes, por: str) -> dict[str, Any]:
    import hashlib
    filas = _leer(nombre, contenido)
    cambios: list[dict] = []
    errores: list[dict] = []
    avisos: list[dict] = []
    catal = await catalogo.para_elegir()
    areas = {_plano(a["nombre"]): a["nombre"] for a in catal["areas"]}
    cargos = {_plano(c["nombre"]): c["nombre"] for c in catal["cargos"]}
    ciudades = {_plano(c["ciudad"]) for c in await obtener_todos("SELECT ciudad FROM ciudades_region")}
    vistas: set[str] = set()

    for fila in filas:
        n, ced = fila["_fila"], _cedula(fila.get("cedula"))
        if not ced:
            errores.append({"fila": n, "cedula": "", "mensaje": "Sin cédula."})
            continue
        if ced in vistas:
            errores.append({"fila": n, "cedula": ced, "mensaje": "La cédula se repite en el archivo."})
            continue
        vistas.add(ced)
        u = await obtener_uno(
            """SELECT u.id, u.nombre, u.cargo, u.departamento, j.cedula AS jefe_cedula, u.ciudad,
                      u.bodega, u.centro_costo, u.cliente, u.tipo_contrato, u.contrato_fin
                 FROM users u LEFT JOIN users j ON j.id = u.jefe_id WHERE u.cedula = %s""", (ced,))
        if u is None:
            errores.append({"fila": n, "cedula": ced, "mensaje": "No hay nadie con esa cédula."})
            continue
        for campo in EDITABLES:
            crudo = fila.get(campo)
            if crudo is None or _texto(crudo) == "":
                continue
            antes = u[campo]
            try:
                if campo == "contrato_fin":
                    nuevo = _fecha(crudo).isoformat()
                    antes = antes.isoformat() if antes else None
                elif campo == "tipo_contrato":
                    nuevo = CONTRATOS.get(_plano(crudo))
                    if nuevo is None:
                        raise ValueError
                elif campo == "jefe_cedula":
                    nuevo = _cedula(crudo)
                    if nuevo == ced:
                        errores.append({"fila": n, "cedula": ced, "mensaje": "Nadie puede ser su propio jefe."})
                        continue
                    if not await obtener_uno("SELECT 1 AS x FROM users WHERE cedula = %s AND activo", (nuevo,)):
                        errores.append({"fila": n, "cedula": ced,
                                        "mensaje": f"El jefe {nuevo} no existe o no está activo."})
                        continue
                else:
                    nuevo = _texto(crudo)
                    if campo == "departamento":
                        nuevo = areas.get(_plano(nuevo), nuevo)
                        if _plano(nuevo) not in areas:
                            avisos.append({"fila": n, "cedula": ced,
                                           "mensaje": f"Área nueva «{nuevo}»: se agregará al catálogo."})
                    elif campo == "cargo":
                        nuevo = cargos.get(_plano(nuevo), nuevo)
                        if _plano(nuevo) not in cargos:
                            avisos.append({"fila": n, "cedula": ced,
                                           "mensaje": f"Cargo nuevo «{nuevo}»: se agregará al catálogo."})
                    elif campo == "ciudad":
                        nuevo = nuevo.upper()
                        if _plano(nuevo) not in ciudades:
                            avisos.append({"fila": n, "cedula": ced, "mensaje":
                                           f"La ciudad «{nuevo}» no está registrada: quedará en la sede de Quito."})
            except ValueError:
                errores.append({"fila": n, "cedula": ced,
                                "mensaje": f"{ETIQUETA[campo]}: valor no válido «{_texto(crudo)}»."})
                continue
            if _plano(antes or "") != _plano(nuevo):
                cambios.append({"fila": n, "cedula": ced, "user_id": str(u["id"]), "nombre": u["nombre"],
                                "campo": campo, "etiqueta": ETIQUETA[campo],
                                "antes": antes, "despues": nuevo})

    # Una fila con error no se aplica entera: se quitan sus cambios.
    con_error = {e["cedula"] for e in errores if e["cedula"]}
    aplicables = [c for c in cambios if c["cedula"] not in con_error]
    anio = dt.date.today().year
    async with transaccion():
        siguiente = (await obtener_uno(
            "SELECT COUNT(*) + 1 AS n FROM cargas_masivas WHERE YEAR(subido_en) = %s FOR UPDATE", (anio,)))["n"]
        folio = f"CM-{anio}-{int(siguiente):04d}"
        await ejecutar(
            """INSERT INTO cargas_masivas (folio, archivo, sha256, filas, cambios, errores, subido_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (folio, nombre[:160], hashlib.sha256(contenido).hexdigest(), len(filas),
             json.dumps(aplicables, default=str), json.dumps(errores + avisos, default=str), por))
    return {"folio": folio, "filas": len(filas), "cambios": aplicables, "errores": errores,
            "avisos": avisos, "personas": len({c["cedula"] for c in aplicables})}


# ----------------------------------------------------------------- aplicar
async def aplicar(folio: str, motivo: str, por: str) -> dict[str, int]:
    from .personal import mover_pendientes_de_sede
    if len((motivo or "").strip()) < 10:
        raise ReglaDeNegocio("Indique el motivo (mínimo 10 caracteres).")
    carga = await obtener_uno(
        "SELECT id, estado, cambios FROM cargas_masivas WHERE folio = %s AND tipo = 'actualizacion'", (folio,))
    if carga is None:
        raise ReglaDeNegocio("Esa carga no existe.")
    if carga["estado"] != "revisada":
        raise ReglaDeNegocio(f"Esa carga ya está {carga['estado']}.")
    cambios = json.loads(carga["cambios"]) if isinstance(carga["cambios"], str) else carga["cambios"]
    if not cambios:
        raise ReglaDeNegocio("La carga no tiene cambios que aplicar.")
    por_persona: dict[str, dict[str, Any]] = {}
    for c in cambios:
        por_persona.setdefault(c["user_id"], {})[c["campo"]] = c["despues"]
    trasladadas = 0
    async with transaccion():
        for user_id, campos in por_persona.items():
            antes = await obtener_uno("SELECT COALESCE(region, 'sierra') AS region, cargo, departamento "
                                      "FROM users WHERE id = %s", (user_id,))
            sets, valores = [], []
            for campo, valor in campos.items():
                if campo == "jefe_cedula":
                    sets.append("jefe_id = (SELECT id FROM (SELECT id FROM users WHERE cedula = %s) j)")
                elif campo in EDITABLES:
                    sets.append(f"`{campo}` = %s")
                else:
                    continue
                valores.append(valor)
            await ejecutar(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", (*valores, user_id))
            await catalogo.asegurar(campos.get("cargo", antes["cargo"]),
                                    campos.get("departamento", antes["departamento"]))
            despues = await obtener_uno("SELECT COALESCE(region, 'sierra') AS region FROM users WHERE id = %s",
                                        (user_id,))
            if despues["region"] != antes["region"]:
                trasladadas += 1
                await mover_pendientes_de_sede(user_id)
        await ejecutar(
            """UPDATE cargas_masivas SET estado = 'aplicada', motivo = %s, aplicado_por = %s,
                      aplicado_en = NOW(6) WHERE id = %s""", (motivo.strip(), por, carga["id"]))
    return {"personas": len(por_persona), "cambios": len(cambios), "cambian_de_sede": trasladadas}


async def descartar(folio: str) -> None:
    n = await ejecutar("UPDATE cargas_masivas SET estado = 'descartada' WHERE folio = %s AND estado = 'revisada'",
                       (folio,))
    if not n:
        raise ReglaDeNegocio("Esa carga no se puede descartar.")
