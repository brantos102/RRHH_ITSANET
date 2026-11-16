"""El asistente para quien gestiona: jefes, Talento Humano y administración.

El asistente del colaborador responde sobre lo propio (saldo, solicitudes).
Quien gestiona pregunta otra cosa: «¿dónde veo lo que tengo por aprobar?»,
«rechacé por error», «¿dónde cambio un parámetro?», «¿cómo registro a
alguien?». Aquí se responde eso, con los números de hoy y el enlace a la
pantalla exacta, según lo que cada perfil puede hacer.

Mismo principio que el resto del asistente: reglas en el propio servidor,
nada sale a un servicio externo y no se inventa nada.
"""
from __future__ import annotations

from typing import Any

from ..db import obtener_todos, obtener_uno

GESTIONA = ("jefe", "rrhh", "admin")
TH = ("rrhh", "admin")

# tema: (palabras clave, perfiles que lo ven)
TEMAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "pendientes": (("por aprobar", "por autorizar", "pendientes de aprobacion", "tengo pendiente",
                    "que tengo", "donde apruebo", "como apruebo", "aprobar solicitud", "aprobar",
                    "autorizar", "bandeja", "pendientes", "que hay pendiente", "donde veo"), GESTIONA),
    "corregir_rechazo": (("rechace", "por error", "me equivoque", "deshacer", "revertir",
                          "corregir rechazo", "corregir la decision", "cambiar la decision",
                          "volver a aprobar", "rechazada por error", "aprobar una rechazada"), GESTIONA),
    "equipo": (("calendario", "mi equipo", "quien falta", "periodos del equipo", "saldos del equipo",
                "ausencias del equipo"), GESTIONA),
    "parametros": (("parametro", "parametros", "configuracion", "configurar", "anticipacion",
                    "bloque minimo", "dias minimos", "politica", "regla", "reglas"), TH),
    "tipos_permiso": (("tipo de permiso", "tipos de permiso", "tipos de solicitud", "descuenta",
                       "remunerado", "lineamiento", "lineamientos"), TH),
    "registrar_persona": (("registrar persona", "registrar personas", "personas nuevas", "nuevo colaborador",
                           "nueva persona", "dar de alta", "crear usuario", "faltan personas", "nomina",
                           "agregar persona", "ingreso de personal"), TH),
    "masivo": (("masiva", "masivo", "varias personas", "muchas personas", "actualizacion masiva"), TH),
    "catalogo": (("cargos", "areas", "catalogo", "unificar", "renombrar cargo", "renombrar area"), TH),
    "baja": (("dar de baja", "baja", "renuncia", "desvincul", "registrar salida", "ya no trabaja",
              "fin de contrato", "despido"), TH),
    "acceso": (("no puede entrar", "no le llega", "codigo de acceso", "registrar correo", "correo de",
                "cerrar sesiones", "perdio el celular", "sin correo"), TH),
    "firmas": (("escaneo", "escanear", "documentos firmados", "subir escaneo", "imprimir", "firma",
                "firmar", "fecha anterior"), TH),
    "exportar": (("exportar", "descargar datos", "reporte", "reportes", "informe", "excel de"), GESTIONA),
    "tableros": (("tablero", "tableros", "indicador", "indicadores", "grafico", "estadistica"), TH),
    "jefaturas": (("jefatura", "jefaturas", "asignar jefe", "cambiar jefe", "asignar equipo"), TH),
    "anulaciones": (("anulacion", "anulaciones", "anular"), TH),
    "emergentes": (("emergente", "emergentes", "menos de 7", "menos dias"), TH),
    "asistente_admin": (("ensenar al asistente", "respuesta del asistente", "agregar respuesta",
                         "preguntas sin respuesta"), TH),
}

SUGERENCIAS_TH = ["¿Qué tengo pendiente?", "Rechacé una solicitud por error", "¿Dónde cambio un parámetro?",
                  "Registrar personas nuevas", "Dar de baja a alguien", "Exportar datos"]
SUGERENCIAS_JEFE = ["¿Qué tengo por aprobar?", "Rechacé una solicitud por error", "Calendario del equipo",
                    "¿Cuántos días de vacaciones tengo?", "¿En qué va mi solicitud?"]


def sugerencias(rol: str) -> list[str] | None:
    return SUGERENCIAS_TH if rol in TH else SUGERENCIAS_JEFE if rol == "jefe" else None


def tema(texto_normal: str, rol: str) -> tuple[str | None, int]:
    t = f" {texto_normal} "
    mejor, puntos = None, 0
    for nombre, (claves, perfiles) in TEMAS.items():
        if rol not in perfiles:
            continue
        p = sum(2 if " " in c else 1 for c in claves if c in t)
        if p > puntos:
            mejor, puntos = nombre, p
    return mejor, puntos


def _r(rol: str, texto: str, detalles: list[str] | None = None,
       acciones: list[dict] | None = None) -> dict[str, Any]:
    return {"texto": texto, "detalles": detalles or [], "acciones": acciones or [],
            "derivar": False, "sugerencias": sugerencias(rol)}


def _n(valor: Any) -> int:
    return int(valor or 0)


# ---------------------------------------------------------------- respuestas
async def _pendientes(u: dict) -> dict:
    rol = u["rol"]
    del_jefe = _n((await obtener_uno(
        "SELECT COUNT(*) AS n FROM requests WHERE estado = 'pendiente_jefe' AND jefe_id = %s",
        (str(u["id"]),)))["n"])
    if rol == "jefe":
        texto = (f"Tiene {del_jefe} solicitud(es) de su equipo por aprobar." if del_jefe
                 else "No tiene solicitudes de su equipo por aprobar.")
        return _r(rol, texto, [
            "Están en el menú: Jefe › Por autorizar (el número indica cuántas hay).",
            "También le llega un correo con un enlace para revisar y decidir.",
            "Al aprobar puede elegir quién cubre el puesto.",
            "Si rechazó alguna por error, en esa misma pantalla, abajo: «Rechazadas en los últimos 30 días».",
        ], [{"texto": "Ir a Por autorizar", "url": "dashboard.html#aprobaciones"}])

    from ..routers.pendientes import SQL_PENDIENTES, _filtro_sede
    from . import sedes as reglas_sedes
    filtro, params = _filtro_sede(u, "mia", await reglas_sedes.nombres())
    conteo = {f["tipo"]: _n(f["n"]) for f in await obtener_todos(
        f"SELECT tipo, COUNT(*) AS n FROM ({SQL_PENDIENTES} WHERE {filtro}) x GROUP BY tipo", params)}
    anulaciones = _n((await obtener_uno(
        "SELECT COUNT(*) AS n FROM requests WHERE estado = 'pendiente_anulacion'"))["n"])
    partes = [(conteo.get("solicitud", 0), "solicitud(es) por autorizar"),
              (conteo.get("cambio_ficha", 0), "cambio(s) de ficha por confirmar"),
              (conteo.get("chat", 0), "consulta(s) del chat sin responder"),
              (conteo.get("firma", 0), "documento(s) por firmar o escanear"),
              (anulaciones, "pedido(s) de anulación")]
    hay = [f"{n} {que}" for n, que in partes if n]
    if del_jefe:
        hay.append(f"{del_jefe} de su propio equipo, como jefe")
    texto = ("En su sede tiene: " + "; ".join(hay) + ".") if hay else "No tiene nada pendiente en su sede. 🎉"
    return _r(rol, texto, [
        "Todo junto, por sede: Talento Humano › Pendientes por sede. «Tomar» avisa a sus compañeros "
        "que usted lo está revisando; «Atender» lo resuelve.",
        "Las solicitudes que ya aprobó el jefe: Talento Humano › Por autorizar.",
        "Las vacaciones de menos días que el bloque mínimo llegan con la etiqueta «Vacaciones emergentes».",
    ], [{"texto": "Pendientes por sede", "url": "administracion.html#pendientes"},
        {"texto": "Por autorizar", "url": "dashboard.html#aprobaciones"},
        *([{"texto": "Anulaciones", "url": "dashboard.html#anulaciones"}] if anulaciones else [])])


async def _corregir_rechazo(u: dict) -> dict:
    n = _n((await obtener_uno(
        """SELECT COUNT(*) AS n FROM requests
            WHERE estado = 'rechazado' AND rechazado_en >= NOW(6) - INTERVAL 30 DAY
              AND user_id <> %s AND (%s OR rechazado_por = %s
                   OR (rechazado_en_etapa = 'jefe' AND jefe_id = %s))""",
        (str(u["id"]), u["rol"] in TH, str(u["id"]), str(u["id"]))))["n"])
    return _r(u["rol"], "Un rechazo por error se corrige, hasta 30 días después:", [
        "Vaya a Por autorizar y abra, abajo, «Rechazadas en los últimos 30 días»"
        + (f" (hay {n})." if n else "."),
        "Pulse «Corregir y aprobar» y escriba por qué corrige: queda en la bitácora.",
        "La solicitud vuelve a la etapa en que se rechazó y se aprueba ahí: si la corrige el jefe, "
        "pasa a Talento Humano; si la corrige Talento Humano, queda aprobada (con su código QR).",
        "La corrige quien la rechazó, el jefe inmediato o Talento Humano. La persona recibe el aviso.",
    ], [{"texto": "Ir a Por autorizar", "url": "dashboard.html#aprobaciones"}])


def _equipo(u: dict) -> dict:
    return _r(u["rol"], "Para ver a su equipo:", [
        "Jefe › Calendario: quién falta y cuándo, por mes y por departamento.",
        "Jefe › Períodos del equipo: saldo, antigüedad, fines de semana pendientes y días en trámite.",
        "Informes › Solicitudes y Por departamento: listados con filtros.",
    ], [{"texto": "Calendario", "url": "equipo.html"},
        {"texto": "Períodos del equipo", "url": "colaboradores.html"}])


async def _parametros(u: dict) -> dict:
    v = {f["clave"]: f["valor"] for f in await obtener_todos(
        """SELECT clave, valor FROM app_config WHERE clave IN
             ('vacaciones_bloque_minimo', 'vacaciones_bloque_sugerido', 'vacaciones_anticipacion_dias',
              'fines_semana_obligatorios', 'vacaciones_feriados_cuentan', 'caducidad_activa')""")}
    si_no = lambda x: "sí" if str(x).lower() in ("true", "1") else "no"  # noqa: E731
    return _r(u["rol"], "Las reglas están en Administración › Parámetros y base legal. Hoy:", [
        f"Bloque mínimo de vacaciones: {v.get('vacaciones_bloque_minimo', '—')} días seguidos "
        f"(se proponen {v.get('vacaciones_bloque_sugerido', '—')}).",
        f"Anticipación sugerida: {v.get('vacaciones_anticipacion_dias', '—')} días (no bloquea).",
        f"Fines de semana obligatorios por período: {v.get('fines_semana_obligatorios', '—')}.",
        f"Feriados dentro de las vacaciones cuentan: {si_no(v.get('vacaciones_feriados_cuentan'))}.",
        f"Caducidad de períodos activa: {si_no(v.get('caducidad_activa'))}.",
        "Cada cambio queda en la bitácora. Los tipos de permiso y los lineamientos tienen su propia pantalla.",
    ], [{"texto": "Parámetros", "url": "administracion.html#configuracion"},
        {"texto": "Tipos de solicitud", "url": "administracion.html#tipos"}])


def _tipos_permiso(u: dict) -> dict:
    return _r(u["rol"], "Los tipos de permiso y lo que se lee antes de enviar:", [
        "Administración › Tipos de solicitud: si piden respaldo o justificación, si descuentan de "
        "vacaciones, si son remunerados y sus topes de días y horas.",
        "Administración › Lineamientos: lo que el colaborador ve bajo «Antes de enviar, tenga presente».",
        "Los cambios rigen para las solicitudes nuevas, no para las ya enviadas.",
    ], [{"texto": "Tipos de solicitud", "url": "administracion.html#tipos"},
        {"texto": "Lineamientos", "url": "administracion.html#lineamientos"}])


def _registrar_persona(u: dict) -> dict:
    return _r(u["rol"], "Para registrar a quien falta en el sistema:", [
        "Una persona: Administración › Usuarios › «+ Nuevo», con su saldo conciliado.",
        "Varias: Administración › Actualización masiva › «Registrar personas nuevas». Puede subir la "
        "nómina completa: quien ya está se reconoce por la cédula y no se toca.",
        "La revisión muestra quién se registraría, con qué saldo, los errores y quién está en el "
        "sistema y no en su archivo. Nada cambia hasta «Registrar personas» con un motivo.",
        "Sin «días disponibles», el saldo se calcula como si no hubiera gozado vacaciones.",
    ], [{"texto": "Registrar personas nuevas", "url": "administracion.html#masivo"},
        {"texto": "Usuarios", "url": "administracion.html#usuarios"}])


def _masivo(u: dict) -> dict:
    return _r(u["rol"], "Para cambiar datos de muchas personas a la vez, sin tocar la base:", [
        "Administración › Actualización masiva › «Descargar plantilla» (de todos, un área o una sede).",
        "Corrija en Excel las columnas en azul: cargo, área, jefe, ciudad, bodega, centro de costo, "
        "cliente, contrato. Una celda vacía no cambia nada.",
        "Súbala: verá el antes y el después de cada persona. Se aplica con un motivo y queda con folio.",
    ], [{"texto": "Actualización masiva", "url": "administracion.html#masivo"}])


def _catalogo(u: dict) -> dict:
    return _r(u["rol"], "Cargos y áreas oficiales: Administración › Cargos y áreas.", [
        "Agregar, renombrar (cambia también las fichas), unificar dos que son el mismo, o desactivar.",
        "Si arriba aparece «En fichas pero no en el catálogo», pulse «Agregarlos al catálogo».",
        "El colaborador elige de esta lista la primera vez que entra; después solo los cambia Talento Humano.",
    ], [{"texto": "Cargos y áreas", "url": "administracion.html#catalogo"}])


def _baja(u: dict) -> dict:
    return _r(u["rol"], "Para registrar la salida de alguien:", [
        "Administración › Usuarios › busque a la persona › registre la salida con la fecha y la causa "
        "(Código del Trabajo).",
        "Su historial se conserva y deja de aparecer en las listas de personal activo.",
        "Las vacaciones no gozadas se pagan en todos los casos (Art. 76): el saldo queda a la vista para la liquidación.",
    ], [{"texto": "Usuarios", "url": "administracion.html#usuarios"}])


def _acceso(u: dict) -> dict:
    return _r(u["rol"], "Si alguien no puede entrar:", [
        "Sin correo registrado no recibe el código: regístrelo en Administración › Usuarios.",
        "Depuración › «No pueden entrar» lista a todos los que están en esa situación.",
        "Si perdió el celular: Administración › Usuarios › «Cerrar sesiones».",
        "El código vale 10 minutos y se pueden pedir 5 por hora.",
    ], [{"texto": "Usuarios", "url": "administracion.html#usuarios"},
        {"texto": "Depuración", "url": "administracion.html#depuracion"}])


def _firmas(u: dict) -> dict:
    return _r(u["rol"], "Documentos para firmar: Talento Humano › Documentos firmados.", [
        "Imprimir: por omisión con la fecha de hoy; una fecha anterior requiere justificación (máximo 3 veces).",
        "Cuando la persona firme, «Registrar firma»; después «Subir escaneo» el mismo día.",
        "Si un escaneo no se sube el día de la firma, llega un aviso cada mañana hasta que se suba.",
    ], [{"texto": "Documentos firmados", "url": "administracion.html#papeles"}])


def _exportar(u: dict) -> dict:
    if u["rol"] == "jefe":
        return _r(u["rol"], "Sus informes:", [
            "Informes › Solicitudes: filtros por estado, tipo, fechas y persona; se descargan en CSV.",
            "Informes › Por departamento: resumen de su gente.",
        ], [{"texto": "Informes", "url": "informes.html"}])
    return _r(u["rol"], "Exportar datos: Informes › Exportar datos.", [
        "Elija qué (personal, saldos, solicitudes, vacaciones gozadas, documentos), de quién (persona, "
        "área, cargo, sede, ciudad, contrato, equipo de un jefe) y el motivo.",
        "Sale en Excel, PDF o CSV con logo y folio EXP-AAAA-NNNN. Queda registrado quién se llevó qué.",
        "Son datos personales (LOPDP): guárdelos solo en equipos de la empresa.",
    ], [{"texto": "Exportar datos", "url": "exportar.html"}])


def _tableros(u: dict) -> dict:
    return _r(u["rol"], "Indicadores: Informes › Tableros.", [
        "Filtros del tablero (sede, área, fechas) para todas las tarjetas; un clic en una barra filtra todo.",
        "Arrastre las tarjetas (⠿), cambie su tamaño (⤢) o amplíelas (⛶). «Configurar» crea gráficos propios.",
    ], [{"texto": "Tableros", "url": "indicadores.html"}])


def _jefaturas(u: dict) -> dict:
    return _r(u["rol"], "Jefes y equipos: Administración › Jefaturas.", [
        "Nombrar una jefatura y asignarle su equipo, por área, cargo o persona.",
        "Para una sola persona, también se cambia el jefe en su ficha (Administración › Usuarios).",
        "Quien no tiene jefe: sus solicitudes las decide Talento Humano en la etapa de jefatura.",
    ], [{"texto": "Jefaturas", "url": "administracion.html#jefaturas"}])


async def _anulaciones(u: dict) -> dict:
    n = _n((await obtener_uno("SELECT COUNT(*) AS n FROM requests WHERE estado = 'pendiente_anulacion'"))["n"])
    return _r(u["rol"], f"Pedidos de anulación por resolver: {n}." if n else "No hay pedidos de anulación.", [
        "Talento Humano › Anulaciones por resolver.",
        "Si la autoriza, se devuelven los días y el código QR deja de servir; si no, escriba el motivo.",
    ], [{"texto": "Anulaciones", "url": "dashboard.html#anulaciones"}])


def _emergentes(u: dict) -> dict:
    return _r(u["rol"], "«Vacaciones emergentes» son las de menos días que el bloque mínimo:", [
        "Llegan primero a Talento Humano, con el motivo que escribió la persona (el respaldo es opcional).",
        "La etiqueta es solo para Talento Humano: el colaborador ve una solicitud normal.",
        "Si la autoriza, pasa al jefe para confirmar quién cubre el puesto.",
    ], [{"texto": "Por autorizar", "url": "dashboard.html#aprobaciones"}])


def _asistente_admin(u: dict) -> dict:
    return _r(u["rol"], "El asistente aprende con sus respuestas: Administración › Asistente.", [
        "Agregue respuestas propias de la empresa con sus palabras clave y un enlace.",
        "Ahí ve también lo que la gente preguntó y el asistente no supo responder (sin decir quién).",
    ], [{"texto": "Asistente", "url": "administracion.html#asistente"}])


RESPUESTAS = {
    "pendientes": _pendientes, "corregir_rechazo": _corregir_rechazo, "equipo": _equipo,
    "parametros": _parametros, "tipos_permiso": _tipos_permiso, "registrar_persona": _registrar_persona,
    "masivo": _masivo, "catalogo": _catalogo, "baja": _baja, "acceso": _acceso, "firmas": _firmas,
    "exportar": _exportar, "tableros": _tableros, "jefaturas": _jefaturas, "anulaciones": _anulaciones,
    "emergentes": _emergentes, "asistente_admin": _asistente_admin,
}


async def responder(nombre: str, usuario: dict) -> dict:
    f = RESPUESTAS[nombre]
    r = f(usuario)
    return await r if hasattr(r, "__await__") else r
