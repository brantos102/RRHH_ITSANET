"""Sesiones por dispositivo: sesión única y cierre a distancia.

Antes el token era «sin estado»: valía hasta que vencía, aunque se cerrara
sesión, y la misma cédula podía estar abierta en cinco equipos a la vez. Si
alguien perdía el celular, no había forma de cortar el acceso.

Ahora cada ingreso crea una fila en `sesiones` y el token lleva su id (`sid`).
Cada petición comprueba que esa sesión siga abierta. Con eso:

  · Una cédula tiene a lo sumo `sesiones_simultaneas` sesiones abiertas (1 por
    defecto). Entrar desde otro dispositivo cierra la más antigua, y se avisa
    por correo: si no fue la persona, se entera enseguida.
  · Volver a entrar desde el MISMO dispositivo (el navegador guarda un
    identificador aleatorio; aquí se guarda solo su huella) reemplaza la
    sesión anterior sin alarmas.
  · El colaborador ve sus dispositivos y cierra los que no reconozca; Talento
    Humano puede cerrar todas las sesiones de alguien que perdió su equipo.

Lo que se registra del dispositivo es lo mínimo para reconocerlo —navegador,
sistema, IP y fecha— (LOPDP, Art. 10).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request, status

from ..audit import ip_del_cliente
from ..db import ejecutar, nuevo_id, obtener_todos, obtener_uno

MENSAJES_CIERRE = {
    "otro_dispositivo": "Su sesión se cerró porque ingresó desde otro dispositivo. "
                        "Si no fue usted, avise a Talento Humano.",
    "mismo_dispositivo": "Su sesión se renovó en este dispositivo. Vuelva a ingresar.",
    "cerrada_por_usuario": "Esta sesión se cerró desde su lista de dispositivos.",
    "talento_humano": "Talento Humano cerró su sesión. Vuelva a ingresar.",
    "salida": "Cerró sesión. Vuelva a ingresar.",
}


def describir_dispositivo(agente: str | None) -> str:
    """«Chrome en Android», «Edge en Windows»… lo justo para reconocerlo."""
    a = agente or ""
    navegador = ("Edge" if "Edg/" in a else "Opera" if "OPR/" in a
                 else "Firefox" if "Firefox/" in a else "Chrome" if "Chrome/" in a
                 else "Safari" if "Safari/" in a else "Navegador")
    sistema = ("Android" if "Android" in a else "iPhone" if "iPhone" in a
               else "iPad" if "iPad" in a else "Windows" if "Windows" in a
               else "Mac" if "Mac OS" in a else "Linux" if "Linux" in a else "")
    return f"{navegador} en {sistema}" if sistema else navegador


def huella(dispositivo_id: str | None) -> str | None:
    limpio = re.sub(r"[^A-Za-z0-9-]", "", dispositivo_id or "")[:80]
    return hashlib.sha256(limpio.encode()).hexdigest() if len(limpio) >= 16 else None


async def maximo_simultaneas() -> int:
    fila = await obtener_uno("SELECT valor FROM app_config WHERE clave = 'sesiones_simultaneas'")
    try:
        return max(1, int((fila or {}).get("valor") or 1))
    except ValueError:
        return 1


async def _cerrar(ids: list[str], motivo: str, por: str | None = None) -> None:
    for sid in ids:
        await ejecutar("""UPDATE sesiones SET cerrada_en = NOW(6), motivo_cierre = %s, cerrada_por = %s
                           WHERE id = %s AND cerrada_en IS NULL""", (motivo, por, sid))


async def abrir(user_id: str, request: Request, expira: datetime,
                dispositivo_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    """Abre la sesión nueva. Devuelve su id y las que se cerraron en OTROS
    dispositivos por superar el máximo (para avisar)."""
    agente = (request.headers.get("user-agent") or "")[:500]
    marca = huella(dispositivo_id)
    abiertas = await obtener_todos(
        """SELECT id, dispositivo, dispositivo_id, ip, ultimo_uso FROM sesiones
            WHERE user_id = %s AND cerrada_en IS NULL AND expira_en > NOW(6)
            ORDER BY ultimo_uso DESC""", (user_id,))
    mismas = [s for s in abiertas if marca and s["dispositivo_id"] == marca]
    otras = [s for s in abiertas if s not in mismas]
    await _cerrar([s["id"] for s in mismas], "mismo_dispositivo")
    sobran = otras[max(await maximo_simultaneas() - 1, 0):]
    await _cerrar([s["id"] for s in sobran], "otro_dispositivo")

    sid = str(nuevo_id())
    await ejecutar(
        """INSERT INTO sesiones (id, user_id, dispositivo, dispositivo_id, user_agent, ip, expira_en)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (sid, user_id, describir_dispositivo(agente), marca, agente, ip_del_cliente(request),
         expira.replace(tzinfo=None)))
    return sid, sobran


async def verificar(sid: str | None, user_id: str) -> None:
    """La sesión del token sigue abierta. Si no, 401 con el motivo."""
    if not sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Su sesión debe renovarse. Vuelva a ingresar.")
    fila = await obtener_uno(
        """SELECT cerrada_en, motivo_cierre, expira_en < NOW(6) AS vencida,
                  ultimo_uso < NOW(6) - INTERVAL 1 MINUTE AS desactualizada
             FROM sesiones WHERE id = %s AND user_id = %s""", (sid, user_id))
    if fila is None or fila["vencida"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Su sesión expiró. Vuelva a ingresar.")
    if fila["cerrada_en"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=MENSAJES_CIERRE.get(fila["motivo_cierre"],
                                                       "Su sesión se cerró. Vuelva a ingresar."))
    if fila["desactualizada"]:
        # Una escritura por minuto como mucho, no una por petición.
        await ejecutar("UPDATE sesiones SET ultimo_uso = NOW(6) WHERE id = %s", (sid,))


async def cerrar(sid: str, motivo: str, por: str | None = None) -> None:
    await _cerrar([sid], motivo, por)


async def listar(user_id: str, actual: str | None = None) -> list[dict[str, Any]]:
    filas = await obtener_todos(
        """SELECT id, dispositivo, ip, creada_en, ultimo_uso, cerrada_en, motivo_cierre,
                  (cerrada_en IS NULL AND expira_en > NOW(6)) AS abierta
             FROM sesiones WHERE user_id = %s
            ORDER BY (cerrada_en IS NULL AND expira_en > NOW(6)) DESC, ultimo_uso DESC
            LIMIT 15""", (user_id,))
    return [{**f, "id": str(f["id"]), "abierta": bool(f["abierta"]),
             "actual": str(f["id"]) == str(actual)} for f in filas]


async def cerrar_todas(user_id: str, motivo: str, por: str | None = None,
                       salvo: str | None = None) -> int:
    abiertas = await obtener_todos(
        "SELECT id FROM sesiones WHERE user_id = %s AND cerrada_en IS NULL", (user_id,))
    ids = [str(s["id"]) for s in abiertas if str(s["id"]) != str(salvo)]
    await _cerrar(ids, motivo, por)
    return len(ids)
