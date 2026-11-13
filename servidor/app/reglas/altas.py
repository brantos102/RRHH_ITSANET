"""Registro masivo de personas nuevas (altas por Excel).

Para completar la base con quienes faltan, sin tocarla a mano:

    1. Talento Humano descarga la plantilla de «Personas nuevas».
    2. Pega ahí su nómina vigente (puede ser la COMPLETA: quien ya está
       registrado se reconoce por la cédula y se omite).
    3. La sube: el sistema dice quién se registraría, quién ya estaba, qué
       filas tienen errores, y quién está en el sistema pero no en el
       archivo (si el archivo es la nómina completa, quizá ya salió).
    4. Si está bien, la aplica con un motivo. Queda con folio CM-AAAA-NNNN,
       igual que las actualizaciones.

El saldo de vacaciones:
  · con «Días disponibles» (el saldo que Talento Humano tiene conciliado),
    se generan los períodos desde la fecha de ingreso y se descuenta lo ya
    gozado, igual que en la carga inicial;
  · sin él, se calcula desde la fecha de ingreso COMO SI NO HUBIERA GOZADO
    NADA. Se avisa en la revisión, porque casi nunca es lo correcto para
    alguien con años en la empresa.

Antes de mostrar la revisión, cada alta se ensaya dentro de una transacción
que se deshace: si el saldo supera lo devengado o la base rechaza algún
dato, se ve en la revisión y no al aplicar.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
from decimal import Decimal, InvalidOperation
from typing import Any

from ..cedula import es_cedula_valida
from ..db import ejecutar, nuevo_id, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio, traducir
from . import catalogo, periodos
from .masivo import CONTRATOS, _cedula, _fecha, _leer_crudas, _plano, _texto

# (campo, encabezado, ancho, obligatorio)
COLUMNAS = [
    ("cedula", "Cédula", 13, True),
    ("nombre", "Apellidos y nombres", 34, True),
    ("fecha_ingreso", "Fecha de ingreso (dd/mm/aaaa)", 16, True),
    ("saldo", "Días de vacaciones disponibles (conciliados)", 18, False),
    ("email", "Correo personal", 28, False),
    ("telefono", "Celular", 14, False),
    ("cargo", "Cargo", 26, False),
    ("departamento", "Área", 22, False),
    ("jefe_cedula", "Cédula del jefe", 15, False),
    ("ciudad", "Ciudad de trabajo", 18, False),
    ("bodega", "Bodega", 16, False),
    ("centro_costo", "Centro de costo", 16, False),
    ("cliente", "Cliente", 16, False),
    ("tipo_contrato", "Tipo de contrato", 16, False),
    ("contrato_fin", "Fin del contrato (dd/mm/aaaa)", 16, False),
    ("fecha_nacimiento", "Fecha de nacimiento (dd/mm/aaaa)", 16, False),
]
ETIQUETA = {c: e.split(" (")[0] for c, e, _, _ in COLUMNAS}
ENCABEZADOS = {_plano(e): c for c, e, _, _ in COLUMNAS}
ENCABEZADOS.update({_plano(e.split(" (")[0]): c for c, e, _, _ in COLUMNAS})
ENCABEZADOS.update({"cedula de identidad": "cedula", "nombre": "nombre", "nombres": "nombre",
                    "nombre completo": "nombre", "apellidos y nombres": "nombre",
                    "fecha ingreso": "fecha_ingreso", "ingreso": "fecha_ingreso",
                    "saldo": "saldo", "dias disponibles": "saldo", "disponible": "saldo",
                    "correo": "email", "email": "email", "telefono": "telefono",
                    "departamento": "departamento", "jefe": "jefe_cedula", "ciudad": "ciudad",
                    "ceco": "centro_costo", "contrato": "tipo_contrato"})
MAX_ALTAS = 1500


class _Ensayo(Exception):
    """Se lanza a propósito para deshacer el ensayo de un alta."""


def _saldo(valor: Any) -> Decimal:
    t = _texto(valor).replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    t = t.replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(t) from exc
    if d < -60 or d > 1200:
        raise ValueError(t)
    return d.quantize(Decimal("0.01"))


# --------------------------------------------------------------- plantilla
async def plantilla() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    elegir = await catalogo.para_elegir()
    ciudades = [c["ciudad"] for c in await obtener_todos("SELECT ciudad FROM ciudades_region ORDER BY ciudad")]
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Personas nuevas"
    hoja.append([e for _, e, _, _ in COLUMNAS])
    azul_oscuro = PatternFill("solid", fgColor="06122B")
    azul = PatternFill("solid", fgColor="1C58D7")
    for i, (_, _, ancho, obligatorio) in enumerate(COLUMNAS, start=1):
        celda = hoja.cell(row=1, column=i)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = azul_oscuro if obligatorio else azul
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.row_dimensions[1].height = 44
    for fila in range(2, 1502):
        for col in (1, 9):                       # cédulas como texto: conservan el cero
            hoja.cell(row=fila, column=col).number_format = "@"
    hoja.freeze_panes = "C2"

    listas = libro.create_sheet("Listas")
    listas.append(["Áreas", "Cargos", "Tipo de contrato", "Ciudades"])
    areas = [a["nombre"] for a in elegir["areas"]]
    cargos = sorted({c["nombre"] for c in elegir["cargos"]})
    contratos = ["indefinido", "eventual", "ocasional", "temporada", "obra_cierta", "prueba",
                 "aprendizaje", "pasantia"]
    for i in range(max(len(areas), len(cargos), len(contratos), len(ciudades), 1)):
        listas.append([x[i] if i < len(x) else None for x in (areas, cargos, contratos, ciudades)])
    for columna, letra, total in (("H", "A", len(areas)), ("G", "B", len(cargos)),
                                  ("N", "C", len(contratos)), ("J", "D", len(ciudades))):
        if not total:
            continue
        v = DataValidation(type="list", formula1=f"Listas!${letra}$2:${letra}${total + 1}",
                           allow_blank=True, showErrorMessage=False)
        v.add(f"{columna}2:{columna}1501")
        hoja.add_data_validation(v)

    leeme = libro.create_sheet("Cómo usarla")
    for linea in [
        "Registro de personas nuevas · ITSANET",
        "",
        "Sirve para completar el sistema con quienes faltan. Puede pegar la NÓMINA COMPLETA:",
        "quien ya está registrado se reconoce por la cédula y no se toca.",
        "",
        "Columnas en azul oscuro: obligatorias (cédula, apellidos y nombres, fecha de ingreso).",
        "Columnas en azul: opcionales.",
        "",
        "· Cédula: 10 dígitos. Si Excel quita el cero inicial, el sistema lo repone.",
        "· Días de vacaciones disponibles: el saldo conciliado por Talento Humano a hoy.",
        "  Si lo deja vacío, se calcula desde la fecha de ingreso como si no hubiera gozado nada.",
        "· Correo personal: donde recibirá su código de acceso. Sin correo no puede entrar todavía;",
        "  se registra después en Administración › Usuarios.",
        "· Cédula del jefe: de alguien ya registrado o de otra fila de este mismo archivo.",
        "· Ciudad de trabajo: define la sede de Talento Humano que la atiende (lista en «Listas»).",
        "",
        "Súbala en Administración › Actualización masiva › Registrar personas nuevas.",
        "Verá quién se registraría antes de aplicar. Nada cambia sin «Aplicar» y un motivo.",
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
def _leer(nombre: str, contenido: bytes) -> list[dict[str, Any]]:
    crudas = _leer_crudas(nombre, contenido, ("Personas nuevas", "Personas"))
    # El encabezado puede no estar en la primera fila (nóminas con título).
    for i, cruda in enumerate(crudas[:10]):
        columnas = [ENCABEZADOS.get(_plano(c)) for c in cruda]
        if "cedula" in columnas and "nombre" in columnas:
            break
    else:
        raise ReglaDeNegocio("No se encontraron las columnas «Cédula» y «Apellidos y nombres». "
                             "Use la plantilla de personas nuevas.")
    filas = []
    for n, cruda in enumerate(crudas[i + 1:], start=i + 2):
        fila = {c: v for c, v in zip(columnas, cruda) if c}
        if any(v not in (None, "") for v in fila.values()):
            filas.append({"_fila": n, **fila})
    if len(filas) > 3000:
        raise ReglaDeNegocio("Máximo 3.000 filas por archivo.")
    return filas


async def _crear(a: dict[str, Any]) -> Decimal:
    """Inserta la persona y genera su saldo. Sin jefe (se asigna al final,
    cuando ya existen todas las del archivo). Devuelve el saldo resultante."""
    await ejecutar(
        """INSERT INTO users (id, cedula, nombre, email, telefono, rol, cargo, departamento,
                              fecha_ingreso, ciudad, bodega, centro_costo, cliente, tipo_contrato,
                              contrato_fin, fecha_nacimiento)
           VALUES (%s, %s, %s, %s, %s, 'empleado', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (a["id"], a["cedula"], a["nombre"], a.get("email"), a.get("telefono"), a.get("cargo"),
         a.get("departamento"), a["fecha_ingreso"], a.get("ciudad") or "QUITO", a.get("bodega"),
         a.get("centro_costo"), a.get("cliente"), a.get("tipo_contrato") or "indefinido",
         a.get("contrato_fin"), a.get("fecha_nacimiento")))
    if a.get("saldo") is not None:
        await periodos.cargar_saldo_inicial(a["id"], Decimal(str(a["saldo"])), 0)
    else:
        await periodos.generar_periodos_vacaciones(a["id"])
    fila = await obtener_uno("SELECT dias_vacaciones AS s FROM users WHERE id = %s", (a["id"],))
    return Decimal(str(fila["s"]))


async def _ensayar(a: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    """Crea la persona dentro de una transacción y la deshace. Devuelve el
    saldo que quedaría, o el motivo por el que la base no la acepta."""
    resultado: dict[str, Any] = {}
    try:
        async with transaccion():
            resultado["saldo"] = await _crear({**a, "id": str(nuevo_id())})
            raise _Ensayo
    except _Ensayo:
        return resultado["saldo"], None
    except ReglaDeNegocio as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001
        e = traducir(exc)
        detalle = getattr(e, "detail", None)
        return None, (detalle.get("mensaje") if isinstance(detalle, dict) else str(detalle or exc))


async def revisar(nombre: str, contenido: bytes, por: str) -> dict[str, Any]:
    filas = _leer(nombre, contenido)
    errores: list[dict] = []
    avisos: list[dict] = []
    altas: list[dict] = []
    ya_registradas: list[dict] = []
    catal = await catalogo.para_elegir()
    areas = {_plano(x["nombre"]): x["nombre"] for x in catal["areas"]}
    cargos = {_plano(x["nombre"]): x["nombre"] for x in catal["cargos"]}
    ciudades = {_plano(c["ciudad"]): c["ciudad"] for c in
                await obtener_todos("SELECT ciudad FROM ciudades_region")}
    hoy = dt.date.today()
    vistas: set[str] = set()
    correos: set[str] = set()

    for fila in filas:
        n, ced = fila["_fila"], _cedula(fila.get("cedula"))
        nombre_p = _texto(fila.get("nombre"))

        def error(mensaje: str) -> None:
            errores.append({"fila": n, "cedula": ced, "nombre": nombre_p, "mensaje": mensaje})

        if not ced:
            error("Sin cédula.")
            continue
        if ced in vistas:
            error("La cédula se repite en el archivo.")
            continue
        vistas.add(ced)
        existe = await obtener_uno(
            "SELECT nombre, activo, fecha_salida FROM users WHERE cedula = %s", (ced,))
        if existe and existe["activo"]:
            ya_registradas.append({"fila": n, "cedula": ced, "nombre": existe["nombre"]})
            continue
        if existe:
            salida = existe["fecha_salida"].strftime("%d/%m/%Y") if existe["fecha_salida"] else "antes"
            error(f"Consta como retirado/a desde {salida}. Si volvió a la empresa, "
                  "reactívelo en Administración › Usuarios (conserva su historial).")
            continue
        if not es_cedula_valida(ced):
            error(f"La cédula {ced} no es válida (revise los dígitos).")
            continue
        if len(nombre_p) < 5:
            error("Falta «Apellidos y nombres».")
            continue
        a: dict[str, Any] = {"fila": n, "cedula": ced, "nombre": nombre_p}
        problema = False
        for campo in ("fecha_ingreso", "contrato_fin", "fecha_nacimiento"):
            crudo = fila.get(campo)
            if crudo in (None, "") or _texto(crudo) == "":
                continue
            try:
                a[campo] = _fecha(crudo)
            except ValueError:
                error(f"{ETIQUETA[campo]}: fecha no válida «{_texto(crudo)}» (use dd/mm/aaaa).")
                problema = True
        if problema:
            continue
        if not a.get("fecha_ingreso"):
            error("Falta la fecha de ingreso.")
            continue
        if a["fecha_ingreso"] > hoy:
            error("La fecha de ingreso es futura: regístrela cuando ingrese.")
            continue
        if a["fecha_ingreso"].year < 1960:
            error("La fecha de ingreso no parece correcta.")
            continue
        if a.get("fecha_nacimiento") and not (1940 <= a["fecha_nacimiento"].year <= hoy.year - 15):
            error("La fecha de nacimiento no parece correcta.")
            continue
        if fila.get("saldo") not in (None, "") and _texto(fila.get("saldo")) != "":
            try:
                a["saldo"] = _saldo(fila["saldo"])
            except ValueError:
                error(f"Días disponibles: número no válido «{_texto(fila['saldo'])}».")
                continue
        correo = _texto(fila.get("email")).lower()
        if correo:
            if "@" not in correo or "." not in correo.split("@")[-1] or " " in correo:
                error(f"Correo no válido «{correo}».")
                continue
            if correo in correos:
                error("El correo se repite en el archivo.")
                continue
            if await obtener_uno("SELECT 1 AS x FROM users WHERE email = %s", (correo,)):
                error(f"El correo {correo} ya lo usa otra persona.")
                continue
            correos.add(correo)
            a["email"] = correo
        tel = "".join(ch for ch in _texto(fila.get("telefono")) if ch.isdigit())
        if tel:
            if len(tel) == 9 and tel.startswith("9"):
                tel = "0" + tel
            a["telefono"] = tel
        for campo in ("bodega", "centro_costo", "cliente"):
            if _texto(fila.get(campo)):
                a[campo] = _texto(fila.get(campo))[:255]
        if _texto(fila.get("tipo_contrato")):
            contrato = CONTRATOS.get(_plano(fila["tipo_contrato"]))
            if contrato is None:
                error(f"Tipo de contrato no válido «{_texto(fila['tipo_contrato'])}».")
                continue
            a["tipo_contrato"] = contrato
        if _texto(fila.get("departamento")):
            texto = _texto(fila["departamento"])
            a["departamento"] = areas.get(_plano(texto), texto)
            if _plano(texto) not in areas:
                avisos.append({"fila": n, "cedula": ced, "nombre": nombre_p,
                               "mensaje": f"Área nueva «{texto}»: se agregará al catálogo."})
        if _texto(fila.get("cargo")):
            texto = _texto(fila["cargo"])
            a["cargo"] = cargos.get(_plano(texto), texto)
            if _plano(texto) not in cargos:
                avisos.append({"fila": n, "cedula": ced, "nombre": nombre_p,
                               "mensaje": f"Cargo nuevo «{texto}»: se agregará al catálogo."})
        texto = _texto(fila.get("ciudad"))
        if texto:
            a["ciudad"] = ciudades.get(_plano(texto), texto.upper())
            if _plano(texto) not in ciudades:
                avisos.append({"fila": n, "cedula": ced, "nombre": nombre_p, "mensaje":
                               f"La ciudad «{texto}» no está registrada: quedará en la sede de Quito."})
        else:
            avisos.append({"fila": n, "cedula": ced, "nombre": nombre_p,
                           "mensaje": "Sin ciudad de trabajo: quedará en la sede de Quito."})
        if _texto(fila.get("jefe_cedula")):
            a["jefe_cedula"] = _cedula(fila["jefe_cedula"])
        if not a.get("email"):
            avisos.append({"fila": n, "cedula": ced, "nombre": nombre_p, "mensaje":
                           "Sin correo: no podrá entrar hasta que se le registre uno."})
        altas.append(a)

    # Jefes: alguien activo ya registrado, o una persona nueva de este archivo.
    nuevas = {a["cedula"] for a in altas}
    for a in list(altas):
        jefe = a.get("jefe_cedula")
        if not jefe:
            continue
        if jefe == a["cedula"]:
            errores.append({"fila": a["fila"], "cedula": a["cedula"], "nombre": a["nombre"],
                            "mensaje": "Nadie puede ser su propio jefe."})
            altas.remove(a)
        elif jefe not in nuevas and not await obtener_uno(
                "SELECT 1 AS x FROM users WHERE cedula = %s AND activo", (jefe,)):
            errores.append({"fila": a["fila"], "cedula": a["cedula"], "nombre": a["nombre"],
                            "mensaje": f"El jefe {jefe} no está registrado ni en este archivo."})
            altas.remove(a)

    if len(altas) > MAX_ALTAS:
        raise ReglaDeNegocio(f"Máximo {MAX_ALTAS} personas nuevas por archivo. Divídalo en partes.")

    # Ensayo: se crea cada una y se deshace, para que el error aparezca aquí.
    for a in list(altas):
        saldo, problema = await _ensayar(a)
        if problema:
            errores.append({"fila": a["fila"], "cedula": a["cedula"], "nombre": a["nombre"],
                            "mensaje": problema})
            altas.remove(a)
            continue
        a["saldo_resultante"] = str(saldo)
        if a.get("saldo") is None:
            avisos.append({"fila": a["fila"], "cedula": a["cedula"], "nombre": a["nombre"], "mensaje":
                           f"Sin días disponibles: se calculan {saldo} desde la fecha de ingreso, "
                           "como si no hubiera gozado vacaciones."})
    # Un jefe que no entró arrastra a su equipo nuevo.
    while True:
        nuevas = {a["cedula"] for a in altas}
        huerfanas = [a for a in altas if a.get("jefe_cedula") and a["jefe_cedula"] not in nuevas
                     and not await obtener_uno("SELECT 1 AS x FROM users WHERE cedula = %s AND activo",
                                               (a["jefe_cedula"],))]
        if not huerfanas:
            break
        for a in huerfanas:
            errores.append({"fila": a["fila"], "cedula": a["cedula"], "nombre": a["nombre"],
                            "mensaje": f"Su jefe ({a['jefe_cedula']}) tiene errores en su fila: corríjalo primero."})
            altas.remove(a)

    # Quién está en el sistema y no en el archivo: si el archivo es la
    # nómina completa, son personas que quizá ya salieron.
    en_archivo = vistas
    activos = await obtener_todos(
        "SELECT cedula, nombre, departamento FROM users WHERE activo AND rol <> 'admin' ORDER BY nombre")
    fuera = [p for p in activos if p["cedula"] not in en_archivo]

    serializables = [{k: (v.isoformat() if isinstance(v, dt.date) else str(v) if isinstance(v, Decimal) else v)
                      for k, v in a.items()} for a in altas]
    anio = hoy.year
    async with transaccion():
        siguiente = (await obtener_uno(
            "SELECT COUNT(*) + 1 AS n FROM cargas_masivas WHERE YEAR(subido_en) = %s FOR UPDATE", (anio,)))["n"]
        folio = f"CM-{anio}-{int(siguiente):04d}"
        await ejecutar(
            """INSERT INTO cargas_masivas (folio, tipo, archivo, sha256, filas, cambios, errores, subido_por)
               VALUES (%s, 'altas', %s, %s, %s, %s, %s, %s)""",
            (folio, nombre[:160], hashlib.sha256(contenido).hexdigest(), len(filas),
             json.dumps(serializables, default=str), json.dumps(errores + avisos, default=str), por))
    return {
        "folio": folio, "tipo": "altas", "filas": len(filas), "altas": serializables,
        "ya_registradas": len(ya_registradas), "errores": errores, "avisos": avisos,
        "no_en_archivo": {"total": len(fuera), "personas": fuera[:300]},
        "activos": len(activos),
    }


# ----------------------------------------------------------------- aplicar
async def aplicar(folio: str, motivo: str, por: str) -> dict[str, int]:
    if len((motivo or "").strip()) < 10:
        raise ReglaDeNegocio("Indique el motivo (mínimo 10 caracteres).")
    carga = await obtener_uno("SELECT id, estado, cambios FROM cargas_masivas WHERE folio = %s AND tipo = 'altas'",
                              (folio,))
    if carga is None:
        raise ReglaDeNegocio("Esa carga no existe.")
    if carga["estado"] != "revisada":
        raise ReglaDeNegocio(f"Esa carga ya está {carga['estado']}.")
    altas = json.loads(carga["cambios"]) if isinstance(carga["cambios"], str) else carga["cambios"]
    if not altas:
        raise ReglaDeNegocio("La carga no tiene personas nuevas que registrar.")
    con_correo = 0
    async with transaccion():
        for a in altas:
            if await obtener_uno("SELECT 1 AS x FROM users WHERE cedula = %s", (a["cedula"],)):
                raise ReglaDeNegocio(f"Fila {a['fila']}: la cédula {a['cedula']} se registró después de la "
                                     "revisión. Vuelva a subir el archivo.")
            a["id"] = str(nuevo_id())
            try:
                await _crear(a)
            except ReglaDeNegocio as exc:
                raise ReglaDeNegocio(f"Fila {a['fila']} ({a['cedula']}): {exc}") from exc
            con_correo += 1 if a.get("email") else 0
        for a in altas:
            if a.get("jefe_cedula"):
                await ejecutar("UPDATE users SET jefe_id = (SELECT id FROM (SELECT id FROM users WHERE cedula = %s) j) "
                               "WHERE id = %s", (a["jefe_cedula"], a["id"]))
            await catalogo.asegurar(a.get("cargo"), a.get("departamento"))
        await ejecutar(
            """UPDATE cargas_masivas SET estado = 'aplicada', motivo = %s, aplicado_por = %s,
                      aplicado_en = NOW(6) WHERE id = %s""", (motivo.strip(), por, carga["id"]))
    return {"personas": len(altas), "con_correo": con_correo, "sin_correo": len(altas) - con_correo}
