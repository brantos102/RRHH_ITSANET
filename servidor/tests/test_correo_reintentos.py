"""El correo se reintenta ante fallos pasajeros y no ante los definitivos."""
from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib
import pytest

from app import correo
from app.config import get_settings


@pytest.fixture
def sin_esperas(monkeypatch):
    monkeypatch.setattr(correo, "ESPERAS", (0, 0, 0))


def _mensaje():
    m = EmailMessage()
    m["To"] = "alguien@itsanet.com.ec"
    m.set_content("hola")
    return m


async def test_un_corte_pasajero_se_reintenta(monkeypatch, sin_esperas):
    llamadas = []

    async def falso(*a, **k):
        llamadas.append(1)
        if len(llamadas) < 3:
            raise aiosmtplib.SMTPResponseException(421, "Try again later")

    monkeypatch.setattr(aiosmtplib, "send", falso)
    await correo._enviar_con_reintentos(_mensaje(), ["a@b.ec"], get_settings(), intentos=4)
    assert len(llamadas) == 3


async def test_la_clave_rechazada_no_se_reintenta(monkeypatch, sin_esperas):
    llamadas = []

    async def falso(*a, **k):
        llamadas.append(1)
        raise aiosmtplib.SMTPAuthenticationError(535, "Username and Password not accepted")

    monkeypatch.setattr(aiosmtplib, "send", falso)
    with pytest.raises(aiosmtplib.SMTPAuthenticationError):
        await correo._enviar_con_reintentos(_mensaje(), ["a@b.ec"], get_settings(), intentos=4)
    assert len(llamadas) == 1


async def test_se_rinde_tras_los_intentos(monkeypatch, sin_esperas):
    llamadas = []

    async def falso(*a, **k):
        llamadas.append(1)
        raise aiosmtplib.SMTPServerDisconnected("se cortó")

    monkeypatch.setattr(aiosmtplib, "send", falso)
    with pytest.raises(aiosmtplib.SMTPServerDisconnected):
        await correo._enviar_con_reintentos(_mensaje(), ["a@b.ec"], get_settings(), intentos=3)
    assert len(llamadas) == 3


class _Ajustes:
    smtp_host = "pro.turbo-smtp.com"
    smtp_port = 587
    smtp_port_alterno = 2525
    smtp_user = "usuario"
    smtp_password = "clave"
    smtp_starttls = "auto"
    smtp_timeout = 1


async def test_si_el_puerto_no_conecta_prueba_el_alterno(monkeypatch, sin_esperas):
    """turboSMTP publica 587 y 2525: si el cortafuegos cierra uno, se usa el otro."""
    puertos = []

    async def falso(*a, port, **k):
        puertos.append(port)
        if port == 587:
            raise aiosmtplib.SMTPConnectTimeoutError("Timed out connecting on port 587")

    monkeypatch.setattr(aiosmtplib, "send", falso)
    await correo._enviar_con_reintentos(_mensaje(), ["a@b.ec"], _Ajustes(), intentos=4)
    assert puertos == [587, 2525]


async def test_sin_alterno_insiste_en_el_mismo_puerto(monkeypatch, sin_esperas):
    puertos = []

    async def falso(*a, port, **k):
        puertos.append(port)
        raise aiosmtplib.SMTPConnectTimeoutError("Timed out")

    ajustes = _Ajustes()
    ajustes.smtp_port_alterno = None
    monkeypatch.setattr(aiosmtplib, "send", falso)
    with pytest.raises(aiosmtplib.SMTPConnectTimeoutError):
        await correo._enviar_con_reintentos(_mensaje(), ["a@b.ec"], ajustes, intentos=3)
    assert puertos == [587, 587, 587]


def test_starttls_automatico_para_proveedores_sin_ssl():
    """«auto»: cifra si el servidor lo ofrece; aiosmtplib lo entiende como None."""
    assert correo.parametros_smtp(_Ajustes())["start_tls"] is None
    assert correo.parametros_smtp(_Ajustes(), 2525)["port"] == 2525
    assert correo.modo_starttls("true") is True and correo.modo_starttls(False) is False
