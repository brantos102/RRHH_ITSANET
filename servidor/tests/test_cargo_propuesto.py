"""Un cargo que no está en la lista se propone desde Mi ficha; al aprobarlo
Talento Humano entra al catálogo y lo ven los compañeros."""
from __future__ import annotations

from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import auth, rrhh_auth  # noqa: F401

CARGO = "Analista de Pruebas Automatizadas"
AREA = "Calidad de Software"


async def test_cargo_nuevo_entra_al_catalogo_al_aprobarlo(cliente, auth, rrhh_auth):
    await ejecutar("DELETE FROM cargos WHERE nombre = %s", (CARGO,))
    await ejecutar("DELETE FROM areas WHERE nombre = %s", (AREA,))
    r = await cliente.post("/mi-ficha/cargo", headers=auth, json={"cargo": CARGO, "departamento": AREA})
    assert r.status_code == 200, r.text
    # Mientras espera no está en la lista de nadie.
    cat = (await cliente.get("/catalogos/cargos", headers=auth)).json()
    assert not any(c["cargo"] == CARGO for c in cat["cargos"])

    bandeja = (await cliente.get("/rrhh/cambios-ficha", headers=rrhh_auth)).json()
    pedidos = {c["campo"]: c for c in bandeja if c["valor_nuevo"] in (CARGO, AREA)}
    assert pedidos["cargo"]["nuevo_en_catalogo"] and pedidos["departamento"]["nuevo_en_catalogo"]

    for campo in ("departamento", "cargo"):
        r = await cliente.post(f"/rrhh/cambios-ficha/{pedidos[campo]['id']}", headers=rrhh_auth,
                               json={"accion": "aprobar"})
        assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "SELECT a.nombre AS area FROM cargos c JOIN areas a ON a.id = c.area_id WHERE c.nombre = %s", (CARGO,))
    assert fila and fila["area"] == AREA
    cat = (await cliente.get("/catalogos/cargos", headers=auth)).json()
    assert any(c["cargo"] == CARGO and c["area"] == AREA for c in cat["cargos"])
    ficha = await obtener_uno("SELECT cargo, departamento FROM users WHERE cedula = '1700000001'")
    assert ficha["cargo"] == CARGO and ficha["departamento"] == AREA
    await ejecutar("DELETE FROM cargos WHERE nombre = %s", (CARGO,))
    await ejecutar("DELETE FROM areas WHERE nombre = %s", (AREA,))


async def test_si_es_lo_mismo_no_pide_nada(cliente, auth):
    yo = await obtener_uno("SELECT cargo, departamento FROM users WHERE cedula = '1700000001'")
    if not yo["cargo"]:
        await ejecutar("UPDATE users SET cargo = 'Operario' WHERE cedula = '1700000001'")
        yo = {"cargo": "Operario", "departamento": yo["departamento"]}
    r = await cliente.post("/mi-ficha/cargo", headers=auth,
                           json={"cargo": yo["cargo"], "departamento": yo["departamento"]})
    assert r.status_code == 200 and "ya consta" in r.json()["mensaje"]
