"""Asistente guiado: responde lo repetitivo y deriva lo demás a una persona.

No es inteligencia artificial y es a propósito (opción A): todo ocurre en el
servidor de la empresa, ningún dato sale a un servicio externo (LOPDP), no
tiene costo por uso y no puede «inventar» un derecho laboral. Responde de dos
fuentes:

  · Lo que el sistema ya sabe de la persona que pregunta —su saldo, sus
    solicitudes, su jefe, sus documentos por firmar— y nada de nadie más.
  · Las respuestas que Talento Humano redacta en Administración › Asistente
    (`asistente_respuestas`), para lo propio de la empresa.

Entiende por palabras clave, sin importar tildes, mayúsculas ni el orden. Si
no sabe, lo dice y ofrece hablar con Talento Humano de su sede; esa pregunta
queda registrada —sin decir quién la hizo— para que Talento Humano agregue la
respuesta que falta.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import booleanos, ejecutar, obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual

router = APIRouter(tags=["Asistente"])
Usuario = Annotated[dict, Depends(usuario_actual)]
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
ESTADOS = {"pendiente_jefe": "espera a su jefe inmediato",
           "pendiente_rrhh": "espera a Talento Humano",
           "pendiente_anulacion": "tiene una anulación en trámite",
           "aprobado": "aprobada", "rechazado": "rechazada", "cancelado": "cancelada"}


def normal(texto: str | None) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]+", " ", t).strip()


def _fecha(d: Any) -> str:
    if not d:
        return "—"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _dias(n: Any) -> str:
    v = float(n or 0)
    return str(int(v)) if v == int(v) else f"{v:.1f}".replace(".", ",")


# ------------------------------------------------------------------ temas
# Cada tema: palabras que lo delatan. Gana el que más coincide; una frase
# de varias palabras pesa más que una suelta.
TEMAS: dict[str, tuple[str, ...]] = {
    "saldo": ("saldo", "cuantos dias", "dias me quedan", "dias tengo", "dias de vacaciones",
              "me quedan", "acumulad", "vacaciones tengo"),
    "solicitudes": ("mi solicitud", "mis solicitudes", "estado", "aprobaron", "aprobada",
                    "rechaz", "pendiente", "en que va", "como va", "tramite"),
    "pedir_vacaciones": ("pedir vacaciones", "solicitar vacaciones", "sacar vacaciones",
                         "tomar vacaciones", "como pido vacaciones", "quiero vacaciones"),
    "permisos": ("permiso", "medico", "cita", "calamidad", "maternidad", "paternidad",
                 "matrimonio", "fallecimiento", "enfermedad", "licencia", "justificar"),
    "jefe": ("mi jefe", "jefe inmediato", "quien aprueba", "quien me aprueba", "supervisor"),
    "documentos": ("firmar", "firma", "documento", "constancia", "papel", "imprimir"),
    "feriados": ("feriado", "festivo", "no laborable", "asueto", "puente"),
    "como_se_cuentan": ("fin de semana", "fines de semana", "como se cuentan", "como cuentan",
                        "dias calendario", "cuentan los dias", "feriado dentro",
                        "se descuentan", "me descuentan", "sabado y domingo"),
    "garita": ("qr", "garita", "salir", "salida", "codigo qr", "guardia"),
    "mis_datos": ("mi correo", "cambiar correo", "telefono", "direccion", "mis datos",
                  "mi ficha", "actualizar datos", "mi cargo", "mi area"),
    "dispositivos": ("sesion", "dispositivo", "celular", "robaron", "perdi", "computadora",
                     "otro equipo"),
    "talento_humano": ("talento humano", "rrhh", "recursos humanos", "hablar con", "contacto",
                       "persona", "humano", "ayuda"),
}

SUGERENCIAS = ["¿Cuántos días de vacaciones tengo?", "¿En qué va mi solicitud?",
               "¿Cómo pido vacaciones?", "Permiso médico", "¿Qué debo firmar?",
               "Próximos feriados"]


def _tema(texto: str) -> tuple[str | None, int]:
    t = f" {normal(texto)} "
    mejor, puntos = None, 0
    for tema, claves in TEMAS.items():
        p = sum(2 if " " in c else 1 for c in claves if c in t)
        if p > puntos:
            mejor, puntos = tema, p
    return mejor, puntos


async def _respuesta_de_rrhh(texto: str) -> tuple[dict | None, int]:
    t = f" {normal(texto)} "
    mejor, puntos = None, 0
    for r in await obtener_todos(
            "SELECT * FROM asistente_respuestas WHERE activo ORDER BY orden, id"):
        claves = [normal(c) for c in (r["palabras_clave"] or "").split(",") if normal(c)]
        p = sum(2 if " " in c else 1 for c in claves if c in t)
        if p > puntos:
            mejor, puntos = r, p
    return mejor, puntos


def _r(texto: str, *, detalles: list[str] | None = None, acciones: list[dict] | None = None,
       derivar: bool = False) -> dict:
    return {"texto": texto, "detalles": detalles or [], "acciones": acciones or [],
            "derivar": derivar, "sugerencias": SUGERENCIAS}


HABLAR = {"texto": "Hablar con Talento Humano", "accion": "hablar"}


# --------------------------------------------------------- cada respuesta
async def _saldo(u: dict) -> dict:
    f = await obtener_uno(
        """SELECT dias_vacaciones,
                  (SELECT COALESCE(SUM(dias_solicitados), 0) FROM requests
                    WHERE user_id = u.id AND tipo = 'vacacion'
                      AND estado IN ('pendiente_jefe', 'pendiente_rrhh')) AS en_tramite,
                  (SELECT MIN(vence_en) FROM vacation_periods
                    WHERE user_id = u.id AND NOT caducado AND dias_saldo > 0) AS vence
             FROM users u WHERE u.id = %s""", (str(u["id"]),))
    detalles = []
    if float(f["en_tramite"] or 0):
        detalles.append(f"{_dias(f['en_tramite'])} día(s) están en solicitudes todavía en trámite.")
    if f["vence"]:
        detalles.append(f"El período más antiguo con saldo vence el {_fecha(f['vence'])}.")
    return _r(f"Tiene {_dias(f['dias_vacaciones'])} día(s) de vacaciones disponibles.",
              detalles=detalles,
              acciones=[{"texto": "Ver de dónde sale mi saldo", "url": "dashboard.html"}])


async def _solicitudes(u: dict) -> dict:
    filas = await obtener_todos(
        """SELECT folio, tipo, estado, fecha_inicio, fecha_fin, motivo_rechazo
             FROM requests WHERE user_id = %s ORDER BY created_at DESC LIMIT 3""", (str(u["id"]),))
    if not filas:
        return _r("Todavía no tiene solicitudes registradas.",
                  acciones=[{"texto": "Hacer una solicitud", "url": "dashboard.html"}])
    detalles = []
    for f in filas:
        que = "Vacaciones" if f["tipo"] == "vacacion" else "Permiso"
        linea = (f"N.º {f['folio']} · {que} del {_fecha(f['fecha_inicio'])} al "
                 f"{_fecha(f['fecha_fin'])}: {ESTADOS.get(f['estado'], f['estado'])}")
        if f["estado"] == "rechazado" and f["motivo_rechazo"]:
            linea += f" (motivo: {f['motivo_rechazo']})"
        detalles.append(linea + ".")
    return _r("Sus últimas solicitudes:", detalles=detalles,
              acciones=[{"texto": "Ver mis solicitudes", "url": "dashboard.html"}])


async def _pedir_vacaciones(u: dict) -> dict:
    c = await obtener_uno("""SELECT cfg_int('vacaciones_anticipacion_dias') AS antic,
                                    cfg_int('vacaciones_bloque_minimo') AS bloque""")
    return _r("Para pedir vacaciones:", detalles=[
        "En «Mi panel», pulse «Nueva solicitud» y elija Vacaciones.",
        f"Pídalas con al menos {c['antic']} días de anticipación.",
        f"Se recomienda tomarlas en bloques de {c['bloque']} días o más.",
        "Al elegir las fechas el sistema le muestra cuántos días descuenta y su saldo.",
        "La aprueba su jefe inmediato y luego Talento Humano; recibirá un correo en cada paso.",
    ], acciones=[{"texto": "Ir a Mi panel", "url": "dashboard.html"}])


async def _permisos(u: dict, texto: str) -> dict:
    tipos = await obtener_todos(
        """SELECT nombre, descripcion, requiere_adjunto, guia_adjuntos, max_dias, max_horas,
                  remunerado FROM permission_types WHERE activo ORDER BY orden""")
    t = normal(texto)
    palabras = [p for p in t.split() if len(p) > 3 and p not in ("permiso", "permisos", "como", "pido")]
    hallado = [x for x in tipos if any(p in normal(x["nombre"]) for p in palabras)]
    if not hallado:
        return _r("Estos son los tipos de permiso. Escriba cuál le interesa (por ejemplo, «permiso médico»):",
                  detalles=[x["nombre"] for x in tipos[:12]],
                  acciones=[{"texto": "Hacer una solicitud", "url": "dashboard.html"}])
    detalles = []
    for x in hallado[:3]:
        partes = [x["nombre"] + ":"]
        if x["max_dias"]:
            partes.append(f"hasta {_dias(x['max_dias'])} día(s)")
        if x["max_horas"]:
            partes.append(f"hasta {_dias(x['max_horas'])} hora(s)")
        partes.append("con remuneración" if x["remunerado"] else "sin remuneración")
        if x["requiere_adjunto"]:
            partes.append("· requiere respaldo" + (f" ({x['guia_adjuntos']})" if x["guia_adjuntos"] else ""))
        detalles.append(" ".join(partes))
    return _r("Esto es lo que necesita:", detalles=detalles,
              acciones=[{"texto": "Hacer la solicitud", "url": "dashboard.html"}])


async def _jefe(u: dict) -> dict:
    j = await obtener_uno("""SELECT j.nombre, j.cargo FROM users u JOIN users j ON j.id = u.jefe_id
                              WHERE u.id = %s""", (str(u["id"]),))
    if not j:
        return _r("No tiene jefe inmediato registrado. Mientras tanto, sus solicitudes las "
                  "decide Talento Humano. Puede indicar quién es desde «Mi ficha».",
                  acciones=[{"texto": "Ir a Mi ficha", "url": "mi-ficha.html"}, HABLAR])
    return _r(f"Su jefe inmediato es {j['nombre']}" + (f" ({j['cargo']})." if j["cargo"] else "."),
              detalles=["Él o ella aprueba primero sus permisos y vacaciones.",
                        "Si no es correcto, pida la corrección desde «Mi ficha»."],
              acciones=[{"texto": "Ir a Mi ficha", "url": "mi-ficha.html"}])


async def _documentos(u: dict) -> dict:
    filas = await obtener_todos(
        """SELECT i.folio, i.tipo FROM informes_firmados i
             LEFT JOIN requests r ON r.id = i.request_id
            WHERE i.user_id = %s AND i.firmado_en IS NULL
              AND (i.tipo = 'trazabilidad' OR r.estado = 'aprobado')
            ORDER BY i.emitido_en DESC LIMIT 5""", (str(u["id"]),))
    sede = (await obtener_uno("SELECT sede FROM regiones WHERE codigo = %s",
                              (u.get("region") or "sierra",)) or {}).get("sede")
    if not filas:
        return _r("No tiene documentos pendientes de firma.",
                  acciones=[{"texto": "Ver mis documentos", "url": "dashboard.html#papeles"}])
    nombres = {"trazabilidad": "Constancia de goce de vacaciones",
               "solicitud": "Solicitud y constancia de vacaciones"}
    return _r(f"Tiene {len(filas)} documento(s) por firmar en Talento Humano"
              + (f" de {sede}." if sede else "."),
              detalles=[f"{nombres.get(f['tipo'], f['tipo'])} · folio {f['folio']}" for f in filas]
              + ["Talento Humano los imprime; usted solo se acerca a firmarlos."],
              acciones=[{"texto": "Ver mis documentos", "url": "dashboard.html#papeles"}])


async def _feriados(u: dict) -> dict:
    filas = await obtener_todos(
        """SELECT fecha, nombre FROM feriados WHERE activo AND fecha >= CURRENT_DATE()
            ORDER BY fecha LIMIT 4""")
    if not filas:
        return _r("No hay feriados registrados próximamente.")
    return _r("Próximos días no laborables:",
              detalles=[f"{_fecha(f['fecha'])}: {f['nombre']}" for f in filas])


def _como_se_cuentan() -> dict:
    return _r("Las vacaciones se cuentan en días calendario: todos los días entre la fecha de "
              "inicio y la de fin, incluidos sábados, domingos y feriados (Art. 69 del Código del "
              "Trabajo). Es fin − inicio + 1, igual que en la hoja de Talento Humano.",
              detalles=["Del lunes 1 al domingo 14: 14 días.",
                        "Del lunes al viernes: 5 días; el fin de semana siguiente no se "
                        "descuenta porque vuelve a trabajar el lunes.",
                        "En cada período deben caer al menos dos fines de semana completos "
                        "(sábado y domingo) dentro de sus vacaciones.",
                        "Los permisos, en cambio, cuentan solo días hábiles."])


def _garita() -> dict:
    return _r("Para salir de la empresa durante un permiso:", detalles=[
        "Cuando su solicitud queda aprobada recibe un código QR por correo.",
        "También lo encuentra en «Mi panel», en la solicitud aprobada.",
        "Muéstrelo en garita al salir; el guardia lo escanea.",
        "El código solo vale en las fechas y horas aprobadas.",
    ], acciones=[{"texto": "Ir a Mi panel", "url": "dashboard.html"}])


def _mis_datos() -> dict:
    return _r("Sus datos se actualizan en «Mi ficha»:", detalles=[
        "Teléfonos, domicilio y contactos de emergencia los cambia usted directamente.",
        "El correo se cambia ahí y rige al abrir el enlace que llega a la dirección nueva.",
        "Su jefe y sus fechas los revisa Talento Humano antes de que rijan.",
        "Su cargo y su área los administra Talento Humano: si no corresponden, escríbales por aquí.",
    ], acciones=[{"texto": "Ir a Mi ficha", "url": "mi-ficha.html"}])


def _dispositivos() -> dict:
    return _r("Su cuenta puede estar abierta en un solo dispositivo a la vez.", detalles=[
        "Si entra desde otro equipo, el anterior se cierra y le llega un correo.",
        "En «Mi ficha › Mis dispositivos» ve dónde está abierta y puede cerrar cualquiera.",
        "Si perdió el celular o se lo robaron, avise de inmediato a Talento Humano: "
        "puede cerrar todas sus sesiones.",
    ], acciones=[{"texto": "Mis dispositivos", "url": "mi-ficha.html"}, HABLAR])


def _talento_humano() -> dict:
    return _r("Puede escribirle a Talento Humano de su sede por este mismo chat; "
              "le responden aquí y le avisamos por correo.", acciones=[HABLAR], derivar=True)


# ------------------------------------------------------------------ rutas
class Pregunta(BaseModel):
    texto: str = Field(..., min_length=1, max_length=300)


@router.get("/asistente/inicio")
async def inicio(usuario: Usuario) -> dict:
    nombre = (usuario.get("nombre") or "").split()
    return _r(f"Hola. Soy el asistente de Talento Humano. Puedo decirle su saldo, cómo va su "
              "solicitud, qué necesita para un permiso y más. ¿En qué le ayudo?"
              if nombre else "¿En qué le ayudo?")


async def _guardar(tema: str, respondida: bool, texto: str | None, region: str | None) -> None:
    try:
        await ejecutar("INSERT INTO asistente_consultas (tema, respondida, texto, region) "
                       "VALUES (%s, %s, %s, %s)",
                       (tema, respondida, (texto or "")[:200] if not respondida else None, region))
        await ejecutar("DELETE FROM asistente_consultas WHERE created_at < NOW(6) - INTERVAL 90 DAY")
    except Exception:  # noqa: BLE001 — la estadística no puede tumbar la respuesta
        pass


@router.post("/asistente/preguntar")
async def preguntar(datos: Pregunta, usuario: Usuario) -> dict:
    texto = datos.texto.strip()
    tema, puntos = _tema(texto)
    propia, puntos_propia = await _respuesta_de_rrhh(texto)
    region = usuario.get("region") or "sierra"

    # Lo que redactó Talento Humano gana si coincide al menos igual de bien:
    # conoce mejor que nadie lo propio de la empresa.
    if propia and puntos_propia >= puntos:
        await _guardar(f"rrhh:{propia['id']}", True, None, region)
        acciones = ([{"texto": propia["enlace_texto"] or "Ver más", "url": propia["enlace_url"]}]
                    if propia["enlace_url"] else [])
        return _r(propia["respuesta"], acciones=acciones)

    respuestas = {
        "saldo": lambda: _saldo(usuario), "solicitudes": lambda: _solicitudes(usuario),
        "pedir_vacaciones": lambda: _pedir_vacaciones(usuario),
        "permisos": lambda: _permisos(usuario, texto), "jefe": lambda: _jefe(usuario),
        "documentos": lambda: _documentos(usuario), "feriados": lambda: _feriados(usuario),
    }
    fijas = {"como_se_cuentan": _como_se_cuentan, "garita": _garita, "mis_datos": _mis_datos, "dispositivos": _dispositivos,
             "talento_humano": _talento_humano}
    if tema in respuestas:
        await _guardar(tema, True, None, region)
        return await respuestas[tema]()
    if tema in fijas:
        await _guardar(tema, True, None, region)
        return fijas[tema]()

    await _guardar("sin_respuesta", False, texto, region)
    return _r("No tengo una respuesta para eso todavía. Talento Humano de su sede puede "
              "ayudarle: escríbales por este mismo chat.", acciones=[HABLAR], derivar=True)


# ---------------------------------------------- administración del asistente
class RespuestaRRHH(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=120)
    palabras_clave: str = Field(..., min_length=2, max_length=500)
    respuesta: str = Field(..., min_length=5, max_length=2000)
    enlace_texto: str | None = Field(None, max_length=80)
    enlace_url: str | None = Field(None, max_length=300)
    activo: bool = True
    orden: int = 100


def _enlace_seguro(url: str | None) -> str | None:
    """Solo pantallas del propio sistema o https: nada de javascript:."""
    url = (url or "").strip()
    if not url:
        return None
    if re.match(r"^(https://|[a-z0-9-]+\.html(#[\w-]*)?$)", url, re.I):
        return url
    raise HTTPException(status_code=422, detail={
        "mensaje": "El enlace debe ser una pantalla del sistema (por ejemplo, mi-ficha.html) "
                   "o una dirección https://."})


@router.get("/admin/asistente")
async def ver_asistente(usuario: RRHH) -> dict:
    respuestas = booleanos(await obtener_todos(
        "SELECT * FROM asistente_respuestas ORDER BY orden, id"), "activo")
    sin = await obtener_todos(
        """SELECT texto, COUNT(*) AS veces, MAX(created_at) AS ultima FROM asistente_consultas
            WHERE NOT respondida AND texto IS NOT NULL
              AND created_at > NOW(6) - INTERVAL 90 DAY
            GROUP BY texto ORDER BY veces DESC, ultima DESC LIMIT 30""")
    temas = await obtener_todos(
        """SELECT tema, COUNT(*) AS veces FROM asistente_consultas
            WHERE created_at > NOW(6) - INTERVAL 30 DAY GROUP BY tema ORDER BY veces DESC""")
    return {"respuestas": [{**r, "id": int(r["id"]),
                            "actualizado_por": str(r["actualizado_por"]) if r["actualizado_por"] else None}
                           for r in respuestas],
            "sin_respuesta": [{**s, "veces": int(s["veces"])} for s in sin],
            "temas": [{**t, "veces": int(t["veces"])} for t in temas]}


@router.post("/admin/asistente/respuestas", status_code=201)
async def crear_respuesta(datos: RespuestaRRHH, request: Request, usuario: RRHH) -> dict:
    await ejecutar(
        """INSERT INTO asistente_respuestas (titulo, palabras_clave, respuesta, enlace_texto,
                                             enlace_url, activo, orden, actualizado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (datos.titulo.strip(), datos.palabras_clave.strip(), datos.respuesta.strip(),
         (datos.enlace_texto or "").strip() or None, _enlace_seguro(datos.enlace_url),
         datos.activo, datos.orden, str(usuario["id"])))
    await registrar(request, "asistente_respuesta_creada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"titulo": datos.titulo})
    return {"mensaje": "Respuesta agregada al asistente."}


@router.patch("/admin/asistente/respuestas/{rid}")
async def cambiar_respuesta(rid: int, datos: RespuestaRRHH, request: Request, usuario: RRHH) -> dict:
    n = await ejecutar(
        """UPDATE asistente_respuestas SET titulo = %s, palabras_clave = %s, respuesta = %s,
                  enlace_texto = %s, enlace_url = %s, activo = %s, orden = %s, actualizado_por = %s
            WHERE id = %s""",
        (datos.titulo.strip(), datos.palabras_clave.strip(), datos.respuesta.strip(),
         (datos.enlace_texto or "").strip() or None, _enlace_seguro(datos.enlace_url),
         datos.activo, datos.orden, str(usuario["id"]), rid))
    await registrar(request, "asistente_respuesta_modificada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"id": rid})
    return {"mensaje": "Respuesta actualizada." if n else "Sin cambios."}


@router.delete("/admin/asistente/respuestas/{rid}")
async def borrar_respuesta(rid: int, request: Request, usuario: RRHH) -> dict:
    await ejecutar("DELETE FROM asistente_respuestas WHERE id = %s", (rid,))
    await registrar(request, "asistente_respuesta_borrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"id": rid})
    return {"mensaje": "Respuesta eliminada."}
