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
