"""Una cédula, una sesión: entrar desde otro dispositivo cierra la anterior.

Si roban el celular o la computadora, basta con entrar desde otro equipo
—o que Talento Humano cierre las sesiones— para dejar fuera al robado.
"""
from __future__ import annotations

import pytest

from app import notificaciones
from app.db import ejecutar
from tests.conftest import CEDULA_PRUEBA
from tests.test_ingreso_firmas import rrhh_auth  # noqa: F401

CELULAR = "a1b2c3d4-e5f6-4a7b-8c9d-000000000001"
COMPUTADORA = "a1b2c3d4-e5f6-4a7b-8c9d-000000000002"


@pytest.fixture
def avisos(monkeypatch) -> list[dict]:
    enviados: list[dict] = []

    async def falso(destino, nombre, nuevo, ip, cerradas):
        enviados.append({"destino": destino, "cerradas": cerradas})

    monkeypatch.setattr(notificaciones, "avisar_sesion_en_otro_dispositivo", falso)
    return enviados


@pytest.fixture(autouse=True)
async def _una_sola(empleado):
    await ejecutar("update app_config set valor = '1' where clave = 'sesiones_simultaneas'")
    yield
    await ejecutar("update app_config set valor = '1' where clave = 'sesiones_simultaneas'")


async def _entrar(cliente, codigos, dispositivo: str, cedula: str = CEDULA_PRUEBA) -> dict:
    await cliente.post("/auth/solicitar-token", json={"cedula": cedula})
    r = await cliente.post("/auth/validar-token", json={"cedula": cedula, "codigo": codigos[-1]},
                           headers={"X-Dispositivo": dispositivo,
                                    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0"})
    assert r.status_code == 200, r.text
    return {"h": {"Authorization": f"Bearer {r.json()['access_token']}"}, "json": r.json()}


async def test_entrar_desde_otro_dispositivo_cierra_el_anterior(cliente, codigos, avisos):
    celular = await _entrar(cliente, codigos, CELULAR)
    assert (await cliente.get("/auth/me", headers=celular["h"])).status_code == 200

    compu = await _entrar(cliente, codigos, COMPUTADORA)
    assert compu["json"]["sesiones_cerradas"] == ["Chrome en Android"]
    r = await cliente.get("/auth/me", headers=celular["h"])
    assert r.status_code == 401
    assert "otro dispositivo" in r.json()["detail"]
    assert (await cliente.get("/auth/me", headers=compu["h"])).status_code == 200
    assert avisos and avisos[0]["cerradas"] == ["Chrome en Android"], "se avisa por correo"


async def test_volver_a_entrar_desde_el_mismo_equipo_no_alarma(cliente, codigos, avisos):
    await _entrar(cliente, codigos, CELULAR)
    otra = await _entrar(cliente, codigos, CELULAR)
    assert otra["json"]["sesiones_cerradas"] == []
    assert not avisos


async def test_cerrar_sesion_invalida_el_token(cliente, codigos):
    s = await _entrar(cliente, codigos, CELULAR)
    assert (await cliente.post("/auth/cerrar-sesion", headers=s["h"])).status_code == 204
    assert (await cliente.get("/auth/me", headers=s["h"])).status_code == 401


async def test_con_dos_permitidas_se_cierra_una_desde_la_lista(cliente, codigos, avisos):
    await ejecutar("update app_config set valor = '2' where clave = 'sesiones_simultaneas'")
    celular = await _entrar(cliente, codigos, CELULAR)
    compu = await _entrar(cliente, codigos, COMPUTADORA)
    assert (await cliente.get("/auth/me", headers=celular["h"])).status_code == 200

    lista = (await cliente.get("/auth/mis-sesiones", headers=compu["h"])).json()
    abiertas = [s for s in lista if s["abierta"]]
    assert len(abiertas) == 2 and sum(s["actual"] for s in abiertas) == 1
    otra = next(s for s in abiertas if not s["actual"])
    r = await cliente.post(f"/auth/mis-sesiones/{otra['id']}/cerrar", headers=compu["h"])
    assert r.status_code == 200
    assert (await cliente.get("/auth/me", headers=celular["h"])).status_code == 401


async def test_talento_humano_corta_el_acceso_de_un_equipo_robado(
        cliente, codigos, empleado, rrhh_auth):
    robado = await _entrar(cliente, codigos, CELULAR)
    r = await cliente.post(f"/auth/admin/usuarios/{empleado['id']}/cerrar-sesiones",
                           headers={"Authorization": rrhh_auth["Authorization"]})
    assert r.status_code == 200, r.text
    r = await cliente.get("/auth/me", headers=robado["h"])
    assert r.status_code == 401 and "Talento Humano" in r.json()["detail"]


async def test_un_colaborador_no_cierra_sesiones_ajenas(cliente, codigos, empleado):
    s = await _entrar(cliente, codigos, CELULAR)
    r = await cliente.post(f"/auth/admin/usuarios/{empleado['id']}/cerrar-sesiones", headers=s["h"])
    assert r.status_code == 403


async def test_un_token_sin_sesion_registrada_no_entra(cliente, empleado):
    from app.security import emitir_token
    token, _ = emitir_token(empleado["id"], CEDULA_PRUEBA, "empleado")
    r = await cliente.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
