"""Configuración del primer ingreso y de quién firma por Talento Humano."""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import Sql, persona
from tests.test_folio_calendario import auth  # noqa: F401

CED_TH = "1700000076"


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    fila = await persona(CED_TH, al_existir={"rol": "rrhh"}, nombre="Talento Firma",
                         email="thfirma@api.test", rol="rrhh", region="costa",
                         fecha_ingreso=Sql("current_date() - interval 900 day"))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_TH})
    r = await cliente.post("/auth/validar-token", json={"cedula": CED_TH, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}", "_id": str(fila["id"])}
    await ejecutar("delete from firmantes_rrhh where user_id = %s", (str(fila["id"]),))
    await ejecutar("delete from users where cedula = %s", (CED_TH,))
    await ejecutar("update app_config set valor = 'correo' where clave = 'alta_verificacion'")
    await ejecutar("update app_config set valor = %s where clave = 'ficha_inicial_campos'",
                   ("fecha_nacimiento,fecha_ingreso,jefe,cargo,telefono,emergencia",))


def _h(auth):
    return {"Authorization": auth["Authorization"]}


async def test_talento_humano_ve_la_cobertura_y_cambia_el_modo(cliente, rrhh_auth):
    r = await cliente.get("/admin/ingreso", headers=_h(rrhh_auth))
    assert r.status_code == 200, r.text
    assert r.json()["modo"] == "correo" and "pct_nacimiento" in r.json()["cobertura"]
    r = await cliente.put("/admin/ingreso", headers=_h(rrhh_auth),
                          json={"modo": "nacimiento", "campos": ["telefono", "fecha_nacimiento"]})
    assert r.status_code == 200, r.text
    cfg = (await cliente.get("/admin/ingreso", headers=_h(rrhh_auth))).json()
    assert cfg["modo"] == "nacimiento"
    assert cfg["campos"] == ["fecha_nacimiento", "telefono"], "orden fijo"


async def test_un_colaborador_no_cambia_la_configuracion(cliente, auth):
    r = await cliente.put("/admin/ingreso", headers=auth, json={"modo": "correo", "campos": []})
    assert r.status_code == 403


async def test_una_sola_cabeza_por_sede(cliente, rrhh_auth):
    r = await cliente.post("/admin/firmantes", headers=_h(rrhh_auth), json={
        "region": "costa", "user_id": rrhh_auth["_id"], "cargo_firma": "Jefe de Talento Humano",
        "principal": True})
    assert r.status_code == 201, r.text
    admin_id = (await obtener_uno("select id from users where rol = 'admin' and activo limit 1"))["id"]
    r = await cliente.post("/admin/firmantes", headers=_h(rrhh_auth), json={
        "region": "costa", "user_id": str(admin_id), "principal": True})
    assert r.status_code == 201, r.text
    lista = (await cliente.get("/papeles/firmantes?region=costa", headers=_h(rrhh_auth))).json()
    assert [f["principal"] for f in lista].count(True) == 1
    assert lista[0]["user_id"] == str(admin_id), "el principal va primero"
    await ejecutar("delete from firmantes_rrhh where user_id = %s", (str(admin_id),))


async def test_solo_firma_quien_integra_talento_humano(cliente, rrhh_auth, empleado):
    r = await cliente.post("/admin/firmantes", headers=_h(rrhh_auth), json={
        "region": "sierra", "user_id": empleado["id"]})
    assert r.status_code == 422
