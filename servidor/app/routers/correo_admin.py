"""Correo del sistema: cómo está configurado, qué salió y qué falló, y una
prueba de envío. Para responder «¿le llegó el código?» sin entrar al
servidor. Lo ven Talento Humano y administración.

No muestra la clave ni el usuario completo del proveedor, ni el contenido
de los correos: solo la constancia (destino enmascarado, asunto sin
códigos, resultado).
"""
from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from .. import correo
from ..audit import registrar
from ..config import get_settings
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol

router = APIRouter(tags=["Correo del sistema"])
TH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


@router.get("/admin/correo")
async def estado(usuario: TH, buscar: str | None = None, solo_fallidos: bool = False) -> dict:
    s = get_settings()
    modo = correo.modo_starttls(s.smtp_starttls)
    usuario_smtp = s.smtp_user or ""
    filtro, params = ["TRUE"], []
    if buscar and "@" in buscar:
        filtro.append("destino_hash = %s")
        params.append(hashlib.sha256(buscar.strip().lower().encode()).hexdigest())
    if solo_fallidos:
        filtro.append("resultado = 'fallido'")
    registros = await obtener_todos(
        f"""SELECT creado_en, destino, asunto, resultado, puerto, intentos, error, duracion_ms
              FROM correos_enviados WHERE {' AND '.join(filtro)} ORDER BY id DESC LIMIT 150""", tuple(params))
    resumen = await obtener_uno(
        """SELECT SUM(resultado = 'enviado') AS enviados, SUM(resultado = 'fallido') AS fallidos,
                  MAX(CASE WHEN resultado = 'enviado' THEN creado_en END) AS ultimo_ok,
                  MAX(CASE WHEN resultado = 'fallido' THEN creado_en END) AS ultimo_fallo
             FROM correos_enviados WHERE creado_en > NOW(6) - INTERVAL 7 DAY""")
    return {
        "configuracion": {
            "modo": "Prueba: los correos solo se escriben en el registro, NO salen" if s.email_backend == "console"
                    else "Envío real por SMTP",
            "servidor": s.smtp_host, "puertos": correo.puertos(s),
            "cifrado": "STARTTLS obligatorio" if modo else "sin cifrado" if modo is False
                       else "STARTTLS si el servidor lo ofrece",
            "remitente": s.smtp_remitente,
            "usuario": (usuario_smtp[:4] + "…") if usuario_smtp else "—",
            "clave": "configurada" if s.smtp_password else "FALTA",
        },
        "ultimos_7_dias": {"enviados": int(resumen["enviados"] or 0), "fallidos": int(resumen["fallidos"] or 0),
                           "ultimo_ok": resumen["ultimo_ok"], "ultimo_fallo": resumen["ultimo_fallo"]},
        "registros": registros,
    }


@router.post("/admin/correo/probar")
async def probar(request: Request, usuario: TH) -> dict:
    """Envía un correo de prueba al buzón de quien lo pide y dice si salió y,
    si no, qué revisar (en castellano)."""
    destino = usuario.get("email")
    if not destino:
        fila = await obtener_uno("SELECT email FROM users WHERE id = %s", (usuario["id"],))
        destino = (fila or {}).get("email")
    if not destino:
        return {"enviado": False, "mensaje": "Su ficha no tiene correo: regístrelo para poder probar."}
    titulo = "Prueba del correo del sistema de Permisos y Vacaciones"
    texto = (f"Hola {usuario['nombre']}:\n\nSi lee esto, el sistema envía correos correctamente.\n"
             "Revise también que no haya llegado a la carpeta de spam.\n")
    try:
        await correo.enviar(destino, titulo, texto, intentos=2)
    except Exception as exc:  # noqa: BLE001
        await registrar(request, "correo_prueba_fallida", user_id=str(usuario["id"]), cedula=usuario["cedula"])
        return {"enviado": False,
                "mensaje": f"No salió el correo a {correo.enmascarar(destino)}.",
                "que_revisar": [x for x in correo.por_que_no_sale(exc, get_settings()) if x]}
    await registrar(request, "correo_prueba_enviada", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    consola = get_settings().email_backend == "console"
    return {"enviado": not consola,
            "mensaje": ("El sistema está en modo de prueba (EMAIL_BACKEND=console): el correo NO sale. "
                        "Configure el envío real con despliegue/configurar_correo.sh.") if consola
                       else f"Enviado a {correo.enmascarar(destino)}. Debe llegar en un minuto; revise también el spam."}
