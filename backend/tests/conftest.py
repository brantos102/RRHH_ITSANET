"""Pruebas contra una base PostgreSQL real (no simulada).

Se apuntan a la base local levantada para desarrollo; en CI se apunta a una
instancia efímera. El correo se intercepta para leer el código sin enviarlo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres@/rrhh_v4?host=/var/lib/pgtest&port=55432",
)
os.environ.setdefault("SUPABASE_JWT_SECRET", "secreto-de-prueba-suficientemente-largo-1234")
os.environ.setdefault("EMAIL_BACKEND", "console")
os.environ.setdefault("ENTORNO", "desarrollo")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "")

import httpx  # noqa: E402
from app import correo  # noqa: E402
from app.db import ejecutar, obtener_uno  # noqa: E402
from app.main import app  # noqa: E402

CEDULA_PRUEBA = "1700000001"
CEDULA_SIN_REGISTRO = "0900000001"
CORREO_PRUEBA = "prueba@api.test"


@pytest.fixture
def codigos(monkeypatch) -> list[str]:
    """Captura el OTP en lugar de enviarlo por correo."""
    capturados: list[str] = []

    async def falso_envio(destinatario: str, nombre: str, codigo: str) -> None:
        capturados.append(codigo)

    monkeypatch.setattr(correo, "enviar_otp", falso_envio)
    return capturados


@pytest.fixture
async def cliente(empleado):
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        yield c


@pytest.fixture
async def empleado():
    """Crea un empleado de prueba y limpia todo lo que la prueba genere."""
    await _limpiar()
    fila = await obtener_uno(
        """
        insert into public.users (cedula, nombre, email, rol, fecha_ingreso, telefono)
        values (%s, 'API Empleado', %s, 'empleado',
                (current_date - make_interval(years => 7))::date, '0999123456')
        returning id
        """,
        (CEDULA_PRUEBA, CORREO_PRUEBA),
    )
    user_id = str(fila["id"])
    # Saldo realista: sin esto acumularía los 7 años completos (108 días)
    await obtener_uno("select public.cargar_saldo_inicial(%s, 12.5, 0) as saldo", (user_id,))
    yield {"id": user_id, "cedula": CEDULA_PRUEBA, "email": CORREO_PRUEBA}
    await _limpiar()


async def _limpiar() -> None:
    await ejecutar("delete from public.auth_otp where cedula = any(%s)",
                   ([CEDULA_PRUEBA, CEDULA_SIN_REGISTRO, "0900000001", "1100000007"],))
    await ejecutar(
        "delete from public.notifications where user_id in "
        "(select id from public.users where email like %s)", ("%@api.test",))
    await ejecutar("delete from public.audit_logs where cedula = any(%s)",
                   ([CEDULA_PRUEBA, CEDULA_SIN_REGISTRO, "0900000001", "1100000007"],))
    await ejecutar("delete from public.users where email like %s", ("%@api.test",))
    await ejecutar("delete from auth.users where email like %s", ("%@api.test",))
