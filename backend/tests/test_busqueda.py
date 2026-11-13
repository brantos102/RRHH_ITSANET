"""La búsqueda de personal encontraba de más.

`normalizar_cedula` se queda en nada cuando se busca por texto, y el patrón
`cedula like '%'` coincide con toda la planilla: teclear «zzzz» devolvía las
trescientas cincuenta personas en vez de ninguna. Con una tabla de cinco
filas no se nota; con la nómina entera, la búsqueda deja de servir.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import CEDULA_RRHH_R, rrhh_auth  # noqa: F401


@pytest.fixture
async def gente(empleado):
    """Dos personas más, para que buscar signifique algo."""
    for cedula, nombre, cargo, depto, correo in [
        ("1700000746", "Zoila Paredes Mena", "Analista de Sistemas", "TI", "zoila@itsanet.test"),
        ("1700000753", "Bruno Salcedo Vaca", "Chofer", "LOGISTICA", "bruno@itsanet.test"),
    ]:
        await ejecutar("delete from public.users where cedula = %s", (cedula,))
        await obtener_uno(
            """insert into public.users (cedula, nombre, email, rol, cargo, departamento,
                                         fecha_ingreso)
               values (%s, %s, %s, 'empleado', %s, %s, current_date - 900) returning id""",
            (cedula, nombre, correo, cargo, depto),
        )
    yield
    await ejecutar("delete from public.users where cedula in ('1700000746','1700000753')")


async def test_una_busqueda_sin_coincidencias_no_devuelve_nada(cliente, rrhh_auth, gente):
    r = await cliente.get("/admin/usuarios?q=zzzznoexiste", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert r.json() == [], "una búsqueda sin coincidencias devolvía la planilla entera"


async def test_se_busca_por_nombre(cliente, rrhh_auth, gente):
    r = await cliente.get("/admin/usuarios?q=Zoila", headers=rrhh_auth)
    nombres = [u["nombre"] for u in r.json()]
    assert nombres == ["Zoila Paredes Mena"]


async def test_se_busca_por_cedula_parcial(cliente, rrhh_auth, gente):
    r = await cliente.get("/admin/usuarios?q=17000007", headers=rrhh_auth)
    cedulas = {u["cedula"] for u in r.json()}
    assert {"1700000746", "1700000753"} <= cedulas


@pytest.mark.parametrize("aguja, esperado", [
    ("Chofer", "Bruno Salcedo Vaca"),          # por cargo
    ("LOGISTICA", "Bruno Salcedo Vaca"),       # por área
    ("zoila@itsanet.test", "Zoila Paredes Mena"),  # por correo
])
async def test_se_busca_tambien_por_cargo_area_y_correo(cliente, rrhh_auth, gente,
                                                        aguja, esperado):
    """Quien busca a «el chofer» no se sabe su cédula."""
    r = await cliente.get(f"/admin/usuarios?q={aguja}", headers=rrhh_auth)
    assert esperado in [u["nombre"] for u in r.json()], f"«{aguja}» no encontró a {esperado}"


async def test_sin_busqueda_salen_todos(cliente, rrhh_auth, gente):
    r = await cliente.get("/admin/usuarios", headers=rrhh_auth)
    assert len(r.json()) >= 3
