"""Correos del flujo de aprobación.

Un mismo diseño para todos: encabezado sobrio, los datos de la solicitud en
una tabla y una sola acción clara. Sin imágenes remotas — los clientes de
correo las bloquean y delatarían la apertura del mensaje.
"""
from __future__ import annotations

import logging
from datetime import date

from . import correo, qr
from .config import get_settings

log = logging.getLogger("rrhh.notificaciones")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha(valor: date | str | None) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, str):
        valor = date.fromisoformat(valor[:10])
    return f"{valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def _rango(inicio, fin) -> str:
    return _fecha(inicio) if inicio == fin else f"{_fecha(inicio)} al {_fecha(fin)}"


def _marco(titulo: str, cuerpo: str, accion: tuple[str, str] | None = None) -> str:
    settings = get_settings()
    boton = (
        f"""<tr><td style="padding-top:8px">
              <a href="{accion[1]}" style="display:inline-block;background:#0f172a;color:#fff;
                 text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:600">
                 {accion[0]}</a>
            </td></tr>"""
        if accion else ""
    )
    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:24px;background:#eef1f4;
      font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#0f172a">
  <table role="presentation" style="max-width:560px;margin:0 auto;background:#fff;
         border-radius:14px;padding:32px;border:1px solid #dde3ea">
    <tr><td>
      <p style="margin:0 0 4px;color:#64748b;font-size:12px">{settings.app_nombre}</p>
      <h1 style="margin:0 0 18px;font-size:19px">{titulo}</h1>
      {cuerpo}
    </td></tr>
    {boton}
  </table>
  <p style="max-width:560px;margin:14px auto 0;color:#7c8a9a;font-size:11.5px;text-align:center">
    Mensaje automático. Sus datos se tratan conforme a la Ley Orgánica de Protección de Datos Personales.
  </p>
</body></html>"""


def _tabla(filas: list[tuple[str, str]]) -> str:
    celdas = "".join(
        f"""<tr>
              <td style="padding:7px 0;color:#64748b;font-size:13px;width:38%">{etiqueta}</td>
              <td style="padding:7px 0;font-size:14px">{valor}</td>
            </tr>"""
        for etiqueta, valor in filas
    )
    return f'<table role="presentation" style="width:100%;border-collapse:collapse">{celdas}</table>'


def _detalle(solicitud: dict) -> list[tuple[str, str]]:
    filas = [
        ("Nº de solicitud", str(solicitud.get("folio") or "—")),
        ("Solicitante", solicitud["empleado"]),
        ("Tipo", solicitud.get("categoria") or ("Vacaciones" if solicitud["tipo"] == "vacacion" else "Permiso")),
        ("Fechas", _rango(solicitud["fecha_inicio"], solicitud["fecha_fin"])),
        ("Días", f"{float(solicitud['dias_solicitados']):g}"),
    ]
    if solicitud.get("hora_inicio"):
        filas.append(("Horario", f"{str(solicitud['hora_inicio'])[:5]} a {str(solicitud['hora_fin'])[:5]}"))
    if solicitud.get("reemplazo"):
        filas.append(("Lo cubre", solicitud["reemplazo"]))
    filas.append(("Descripción", solicitud["descripcion"]))
    if solicitud.get("justificacion"):
        filas.append(("Justificación", solicitud["justificacion"]))
    if solicitud.get("es_adelanto"):
        filas.append(("Atención", "Incluye días adelantados: supera el saldo disponible."))
    return filas


def _enlace(token: str, rol: str) -> str:
    return f"{get_settings().app_url.rstrip('/')}/aprobar.html?t={token}&r={rol}"


# --------------------------------------------------------------------------
async def avisar_al_jefe(jefe: dict, solicitud: dict) -> None:
    url = _enlace(str(solicitud["jefe_token"]), "jefe")
    titulo = f"{solicitud['empleado']} solicita {'vacaciones' if solicitud['tipo'] == 'vacacion' else 'un permiso'}"
    cuerpo = (
        f'<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        f"Requiere su aprobación como jefe inmediato.</p>"
        + _tabla(_detalle(solicitud))
        + '<p style="margin:18px 0 0;font-size:13px;color:#64748b">'
          "Abra el enlace para revisarla y decidir.</p>"
    )
    texto = (
        f"{titulo}\n\n"
        + "\n".join(f"{e}: {v}" for e, v in _detalle(solicitud))
        + f"\n\nRevise y decida aquí:\n{url}\n"
    )
    await correo.enviar(jefe["email"], titulo, texto, _marco(titulo, cuerpo, ("Revisar solicitud", url)))


async def avisar_a_rrhh(destinatarios: list[dict], solicitud: dict, jefe: str) -> None:
    url = _enlace(str(solicitud["rrhh_token"]), "rrhh")
    titulo = f"Aprobación de Talento Humano: {solicitud['empleado']}"
    filas = _detalle(solicitud) + [("Aprobada por", jefe)]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "El jefe inmediato ya aprobó esta solicitud. Falta la aprobación de Talento Humano.</p>"
        + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + f"\n\nDecida aquí:\n{url}\n"
    html = _marco(titulo, cuerpo, ("Revisar solicitud", url))

    for persona in destinatarios:
        try:
            await correo.enviar(persona["email"], titulo, texto, html)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo avisar a %s", persona["email"])


async def avisar_excepcion_a_rrhh(
    destinatarios: list[dict], solicitud: dict, empleado_email: str | None
) -> None:
    """Vacaciones fuera de la política: lo decide Talento Humano, no el jefe.

    Un bloque por debajo del mínimo, o días que todavía no se han ganado, se
    apartan de lo pactado, y eso no lo autoriza la jefatura inmediata. Antes
    la solicitud quedaba correctamente en `pendiente_rrhh` pero el correo se
    enviaba al jefe —que no podía hacer nada con ella— y a Talento Humano no
    le llegaba ninguno: la solicitud se quedaba esperando a que alguien
    entrara a mirar la bandeja.

    El empleado va en copia y como dirección de respuesta: así tiene la
    constancia formal en su propio buzón y Talento Humano puede contestarle
    directamente, que es como se resuelven estos casos.
    """
    url = _enlace(str(solicitud["rrhh_token"]), "rrhh")
    emergente = bool(solicitud.get("bloque_menor_justificado"))
    titulo = (
        f"Vacaciones emergentes por autorizar: {solicitud['empleado']}"
        if emergente else
        f"Adelanto de vacaciones por autorizar: {solicitud['empleado']}"
    )

    motivo = (
        "Pide menos días seguidos de los que fija la política, así que no son "
        "vacaciones ordinarias: requieren la autorización de Talento Humano."
        if emergente else
        "Solicita días que todavía no ha ganado. El adelanto lo autoriza "
        "Talento Humano antes que la jefatura."
    )
    filas = _detalle(solicitud)
    if solicitud.get("jefe_nombre"):
        filas.append(("Jefe inmediato", solicitud["jefe_nombre"]))
    if empleado_email:
        filas.append(("Responder a", empleado_email))

    cuerpo = (
        f'<p style="margin:0 0 16px;font-size:14px;color:#475569">{motivo}</p>'
        + _tabla(filas)
        + '<p style="margin:16px 0 0;font-size:13px;color:#64748b">'
        "Si la autoriza, pasa al jefe inmediato para que confirme la cobertura "
        "del puesto y queda registrada como vacaciones emergentes, con su "
        "descuento de días.</p>"
    )
    texto = (
        f"{titulo}\n\n{motivo}\n\n"
        + "\n".join(f"{e}: {v}" for e, v in filas)
        + f"\n\nDecida aquí:\n{url}\n"
    )
    html = _marco(titulo, cuerpo, ("Revisar solicitud", url))

    copia = [empleado_email] if empleado_email else None
    for persona in destinatarios:
        try:
            await correo.enviar(persona["email"], titulo, texto, html,
                                responder_a=empleado_email, copia=copia)
            # La copia al empleado va una sola vez, con el primer destinatario:
            # recibir el mismo aviso tantas veces como gente haya en Talento
            # Humano no es constancia, es ruido.
            copia = None
        except Exception:  # noqa: BLE001
            log.exception("No se pudo avisar a %s", persona["email"])

    if not destinatarios:
        log.warning(
            "La solicitud %s necesita a Talento Humano y no hay nadie registrado "
            "en su región: nadie recibió el aviso", solicitud.get("folio"))


async def avisar_aprobacion(empleado: dict, solicitud: dict) -> None:
    """Al empleado, con su código QR incrustado y adjunto."""
    imagen = qr.png(str(solicitud["qr_hash"]))
    titulo = "Su solicitud fue aprobada"
    filas = _detalle(solicitud) + [("Válido hasta", _fecha(solicitud["fecha_fin"]))]

    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "Su solicitud completó las dos aprobaciones. Presente este código en garita al salir.</p>"
        + _tabla(filas)
        + """<div style="margin-top:22px;text-align:center">
               <img src="cid:qr" alt="Código QR de salida" width="220" height="220"
                    style="border:1px solid #dde3ea;border-radius:12px;padding:10px;background:#fff">
               <p style="margin:10px 0 0;color:#64748b;font-size:12px">
                 También puede mostrarlo desde el sistema, en «Mis solicitudes».</p>
             </div>"""
    )
    texto = (
        f"{titulo}\n\n"
        + "\n".join(f"{e}: {v}" for e, v in filas)
        + "\n\nSu código QR de salida va adjunto a este correo.\n"
    )
    await correo.enviar(
        empleado["email"], titulo, texto, _marco(titulo, cuerpo),
        imagenes={"qr": imagen},
        adjuntos=[("codigo-qr-salida.png", imagen, "image/png")],
    )


async def avisar_rechazo(empleado: dict, solicitud: dict, quien: str, motivo: str) -> None:
    titulo = "Su solicitud fue rechazada"
    filas = _detalle(solicitud) + [("Rechazada por", quien), ("Motivo", motivo or "No especificado")]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "Puede conversarlo con quien la rechazó o enviar una nueva solicitud con otras fechas.</p>"
        + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + "\n"
    await correo.enviar(empleado["email"], titulo, texto, _marco(titulo, cuerpo))


async def avisar_ajuste(destinatarios: list[dict], solicitud: dict, quien: str,
                        motivo: str, resolucion: str) -> None:
    """Al colaborador y a su jefe cuando Talento Humano cambia una ausencia.

    Los dos necesitan enterarse por motivos distintos: el colaborador, para
    saber hasta cuándo está cubierto; el jefe, para no contar con alguien
    que no va a venir.
    """
    titulo = "Se ajustó una ausencia autorizada"
    filas = _detalle(solicitud) + [
        ("Nuevas fechas", f"{_fecha(solicitud['fecha_inicio'])} a {_fecha(solicitud['fecha_fin'])}"),
        ("Ajustada por", quien),
        ("Caso", motivo),
        ("Resolución", resolucion),
    ]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "Talento Humano modificó las fechas de una ausencia ya autorizada. "
        "El registro anterior se conserva en el historial de la solicitud.</p>"
        + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + "\n"

    for destino in destinatarios:
        if destino.get("email"):
            await correo.enviar(destino["email"], titulo, texto, _marco(titulo, cuerpo))


async def avisar_alta_completada(destinatarios: list[dict], nombre: str,
                                 cedula: str, email: str) -> None:
    """A Talento Humano cuando alguien registra su correo por primera vez.

    El sistema ya verifica la dirección de vuelta —sin recibir el código no
    se entra—, pero un correo que alguien declara de sí mismo merece que
    quien lleva el expediente lo mire. Sobre todo si no es el institucional.
    """
    titulo = "Un colaborador completó su ficha"
    filas = [("Colaborador", nombre), ("Cédula", cedula),
             ("Correo registrado", email)]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "Esta persona no tenía correo registrado y acaba de completar sus datos "
        "para poder acceder. Verifique que la dirección corresponda.</p>"
        + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + "\n"
    for destino in destinatarios:
        if destino.get("email"):
            await correo.enviar(destino["email"], titulo, texto, _marco(titulo, cuerpo))


async def confirmar_direccion(destino: str, nombre: str, token: str) -> None:
    """A la dirección nueva, para comprobar que existe y es de quien la declara.

    Es la única barrera que hace falta para un correo: cambiar el propio no
    es una decisión que Talento Humano deba aprobar —nadie conoce mejor su
    buzón—, pero sí hay que comprobar que el buzón es suyo. Hasta que se abra
    este enlace, el correo anterior sigue rigiendo: un dedazo no deja a nadie
    sin poder entrar.
    """
    url = f"{get_settings().app_url.rstrip('/')}/confirmar.html?t={token}"
    titulo = "Confirme su dirección de correo"
    cuerpo = (
        f'<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        f"{nombre}, alguien —quizá usted— registró esta dirección para recibir "
        "los códigos de acceso y los avisos de sus solicitudes. Confírmelo para "
        "que empiece a regir.</p>"
        '<p style="margin:0 0 16px;font-size:13px;color:#64748b">'
        "El enlace vence en 24 horas. Si no fue usted, ignore este mensaje: "
        "no se cambió nada y su correo anterior sigue vigente.</p>"
    )
    texto = (f"{titulo}\n\n{nombre}, confirme esta dirección abriendo:\n{url}\n\n"
             "El enlace vence en 24 horas. Si no fue usted, ignore este mensaje.\n")
    await correo.enviar(destino, titulo, texto, _marco(titulo, cuerpo, ("Confirmar mi correo", url)))


async def avisar_correo_confirmado(destino: str, nombre: str, email: str) -> None:
    """Al correo anterior: si el cambio no fue suyo, tiene que enterarse."""
    if not destino or destino == email:
        return
    titulo = "Su correo de acceso cambió"
    filas = [("Colaborador", nombre), ("Nueva dirección", email)]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "A partir de ahora los códigos de acceso y los avisos van a la dirección "
        "nueva. Si usted no hizo este cambio, escriba a Talento Humano de "
        "inmediato.</p>" + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + "\n"
    await correo.enviar(destino, titulo, texto, _marco(titulo, cuerpo))


async def avisar_correccion_de_ficha(destinatarios: list[dict], nombre: str,
                                     cedula: str, pedidos: list[tuple[str, str]]) -> None:
    """A Talento Humano cuando alguien dice que su cargo o su jefe están mal.

    No es un trámite menor: de quién es jefe de quién depende a dónde va cada
    solicitud a autorizarse. Por eso lo confirma Talento Humano y no se aplica
    solo, y por eso el aviso sale en el momento, no en un informe mensual.
    """
    if not pedidos:
        return
    titulo = f"{nombre} corrige su cargo o su jefe"
    filas = [("Colaborador", nombre), ("Cédula", cedula), *pedidos]
    cuerpo = (
        '<p style="margin:0 0 16px;font-size:14px;color:#475569">'
        "Al entrar por primera vez, esta persona indicó que el dato registrado "
        "no corresponde. Nada cambió todavía: revíselo en «Cambios de ficha» y "
        "confírmelo o recházelo.</p>" + _tabla(filas)
    )
    texto = f"{titulo}\n\n" + "\n".join(f"{e}: {v}" for e, v in filas) + "\n"
    for destino in destinatarios:
        if destino.get("email"):
            await correo.enviar(destino["email"], titulo, texto, _marco(titulo, cuerpo))
