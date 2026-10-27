"""La ficha del colaborador: qué corrige solo, qué revisa Talento Humano y
cómo se cambia el correo.

Reemplaza a actualizar_ficha_libre, solicitar_cambio_ficha,
resolver_cambio_ficha, pedir_confirmacion_correo y confirmar_correo.

Cada campo tiene un nivel en la tabla `campos_ficha`:
  libre        la persona lo corrige directamente (su teléfono, su dirección)
  revision     lo pide la persona y lo aprueba Talento Humano (cargo, jefe)
  confirmado   se aplica al abrir el enlace que llega a la dirección nueva (correo)
  bloqueado    no se cambia desde la ficha

EL NOMBRE DEL CAMPO VA DENTRO DEL SQL. En PostgreSQL se armaba con
format('%I'), que lo citaba como identificador. Aquí se acepta solo si está
en `campos_ficha` Y es una columna real de `users` con forma de nombre de
columna: así un valor manipulado no puede convertirse en SQL.
"""
from __future__ import annotations

import re
from typing import Any

from ..db import ejecutar, nuevo_id, obtener_uno, transaccion
from ..errores import ReglaDeNegocio

_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")


async def _columna_de_users(campo: str) -> str:
    """El nombre de columna, comprobado. Nunca devuelve algo que no lo sea."""
    if not _IDENTIFICADOR.match(campo or ""):
        raise ReglaDeNegocio(f'El campo "{campo}" no forma parte de la ficha')
    existe = await obtener_uno(
        """SELECT 1 AS x FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = %s""",
        (campo,))
    if existe is None:
        raise ReglaDeNegocio(f'El campo "{campo}" no forma parte de la ficha')
    return campo


async def _nivel(campo: str) -> str | None:
    fila = await obtener_uno("SELECT nivel FROM campos_ficha WHERE campo = %s", (campo,))
    return fila["nivel"] if fila else None


def _limpio(valor) -> str:
    """btrim(coalesce(valor, '')) de PostgreSQL: recorta solo espacios."""
    return str(valor if valor is not None else "").strip(" ")


async def actualizar_ficha_libre(user_id, campos: dict[str, Any]) -> dict[str, Any]:
    """Aplica los campos de nivel «libre». Uno de otro nivel detiene todo."""
    async with transaccion():
        for campo, valor in campos.items():
            nivel = await _nivel(campo)
            if nivel is None:
                raise ReglaDeNegocio(f'El campo "{campo}" no forma parte de la ficha')
            # La comprobación vive aquí y no en la ruta: es la última línea, y
            # la única que un cliente alterado no puede saltarse.
            if nivel != "libre":
                raise ReglaDeNegocio(f'El campo "{campo}" no se corrige desde la ficha: '
                                     "requiere validación de Talento Humano")
            columna = await _columna_de_users(campo)
            texto = _limpio(valor)
            await ejecutar(f"UPDATE users SET `{columna}` = %s WHERE id = %s",
                           (texto or None, user_id))
        return await obtener_uno("SELECT * FROM users WHERE id = %s", (user_id,))


async def solicitar_cambio_ficha(user_id, campo: str, valor, motivo: str | None) -> int:
    """Registra un pedido de cambio para que Talento Humano lo revise."""
    nivel = await _nivel(campo)
    if nivel is None:
        raise ReglaDeNegocio(f'El campo "{campo}" no forma parte de la ficha')
    if nivel == "bloqueado":
        raise ReglaDeNegocio(f'El campo "{campo}" no se modifica desde la ficha. '
                             "Escriba a Talento Humano si hay un error.")
    if nivel == "libre":
        raise ReglaDeNegocio(f'El campo "{campo}" se corrige directamente, sin pasar por revisión')
    if nivel == "confirmado":
        raise ReglaDeNegocio(f'El campo "{campo}" no lo aprueba nadie: se confirma desde el '
                             "enlace que llega al correo nuevo")
    nuevo = _limpio(valor)
    if not nuevo:
        raise ReglaDeNegocio("El nuevo valor no puede quedar vacío")

    columna = await _columna_de_users(campo)
    async with transaccion():
        actual = await obtener_uno(f"SELECT CAST(`{columna}` AS CHAR) AS v FROM users WHERE id = %s",
                                   (user_id,))
        anterior = actual["v"] if actual else None
        if anterior == nuevo:
            raise ReglaDeNegocio("El valor es el mismo que ya está registrado")

        # El jefe se señala por su identificador: se comprueba aquí que exista
        # y que no sea la propia persona, para que el error salga al pedirlo y
        # no al aprobarlo.
        if campo == "jefe_id":
            if nuevo == str(user_id):
                raise ReglaDeNegocio("Nadie puede ser su propio jefe")
            if await obtener_uno("SELECT 1 AS x FROM users WHERE id = %s AND activo", (nuevo,)) is None:
                raise ReglaDeNegocio("La jefatura señalada no existe o no está activa")

        await ejecutar(
            """UPDATE cambios_ficha
                  SET estado = 'rechazado', motivo_rechazo = 'Reemplazado por una solicitud posterior',
                      resuelto_en = NOW(6)
                WHERE user_id = %s AND campo = %s AND estado = 'pendiente'""", (user_id, campo))
        from ..db import insertar
        return await insertar(
            """INSERT INTO cambios_ficha (user_id, campo, valor_anterior, valor_nuevo, motivo)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, campo, anterior, nuevo, _limpio(motivo) or None))


async def resolver_cambio_ficha(cambio_id: int, aprobar: bool, por, motivo: str | None) -> dict[str, Any]:
    """Talento Humano aprueba (y aplica) o rechaza un pedido de cambio."""
    async with transaccion():
        cambio = await obtener_uno("SELECT * FROM cambios_ficha WHERE id = %s FOR UPDATE", (cambio_id,))
        if cambio is None:
            raise ReglaDeNegocio("El cambio no existe")
        if cambio["estado"] != "pendiente":
            raise ReglaDeNegocio("Este cambio ya fue resuelto")
        if aprobar:
            # MySQL convierte el texto al tipo de la columna (fecha, id...)
            # al asignarlo; en PostgreSQL hacía falta un cast explícito.
            columna = await _columna_de_users(cambio["campo"])
            await ejecutar(f"UPDATE users SET `{columna}` = %s WHERE id = %s",
                           (cambio["valor_nuevo"], cambio["user_id"]))
            if cambio["campo"] == "email":
                await ejecutar("UPDATE users SET correo_pendiente = FALSE WHERE id = %s",
                               (cambio["user_id"],))
        elif len(_limpio(motivo)) < 5:
            raise ReglaDeNegocio("Indique por qué se rechaza: la persona debe saber qué corregir")
        await ejecutar(
            """UPDATE cambios_ficha
                  SET estado = %s, resuelto_por = %s, resuelto_en = NOW(6), motivo_rechazo = %s
                WHERE id = %s""",
            ("aprobado" if aprobar else "rechazado", por, None if aprobar else _limpio(motivo), cambio_id))
        return await obtener_uno("SELECT * FROM cambios_ficha WHERE id = %s", (cambio_id,))


_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def pedir_confirmacion_correo(user_id, email: str | None, ip: str | None) -> dict[str, Any]:
    """Deja pendiente el correo nuevo hasta que se confirme desde ese buzón."""
    nuevo = _limpio(email).lower()
    if not _CORREO.match(nuevo):
        raise ReglaDeNegocio("La dirección de correo no tiene un formato válido")
    async with transaccion():
        actual = await obtener_uno("SELECT LOWER(email) AS email, id FROM users WHERE id = %s", (user_id,))
        if actual is None or actual["email"] is None:
            raise ReglaDeNegocio("La persona no existe")
        if actual["email"] == nuevo:
            raise ReglaDeNegocio("Ese correo ya es el suyo")
        if await obtener_uno("SELECT 1 AS x FROM users WHERE LOWER(email) = %s AND id <> %s",
                             (nuevo, user_id)):
            raise ReglaDeNegocio("Ese correo ya está registrado por otra persona")
        # Una confirmación viva por persona: pedirla de nuevo invalida la
        # anterior, para que un enlace viejo no aplique una dirección descartada.
        await ejecutar("DELETE FROM confirmaciones_correo WHERE user_id = %s AND confirmado_en IS NULL",
                       (user_id,))
        token = nuevo_id()
        await ejecutar(
            "INSERT INTO confirmaciones_correo (token, user_id, email, ip) VALUES (%s, %s, %s, %s)",
            (token, user_id, nuevo, ip))
        return await obtener_uno("SELECT * FROM confirmaciones_correo WHERE token = %s", (token,))


async def confirmar_correo(token) -> dict[str, Any]:
    """El enlace que llegó a la dirección nueva: recién aquí empieza a regir."""
    async with transaccion():
        fila = await obtener_uno(
            """SELECT * FROM confirmaciones_correo
                WHERE token = %s AND confirmado_en IS NULL AND expira_en > NOW(6) FOR UPDATE""",
            (str(token),))
        if fila is None:
            return {"confirmado": False,
                    "motivo": "El enlace ya se usó o venció. Pida uno nuevo desde su ficha."}
        # Entre el pedido y la confirmación alguien pudo tomar esa dirección.
        if await obtener_uno("SELECT 1 AS x FROM users WHERE LOWER(email) = LOWER(%s) AND id <> %s",
                             (fila["email"], fila["user_id"])):
            return {"confirmado": False,
                    "motivo": "Esa dirección quedó registrada por otra persona. Escriba a Talento Humano."}
        await ejecutar("UPDATE users SET email = %s, correo_pendiente = FALSE WHERE id = %s",
                       (fila["email"], fila["user_id"]))
        await ejecutar("UPDATE confirmaciones_correo SET confirmado_en = NOW(6) WHERE id = %s", (fila["id"],))
        persona = await obtener_uno("SELECT nombre FROM users WHERE id = %s", (fila["user_id"],))
        return {"confirmado": True, "nombre": persona["nombre"], "email": fila["email"]}
