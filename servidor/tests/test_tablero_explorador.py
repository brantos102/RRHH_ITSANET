"""El explorador del tablero: medidas por dimensiones, solo agregados, y los
gráficos que cada quien guarda y comparte."""
from __future__ import annotations

from app.db import ejecutar
from tests.test_reglas_nuevas import CEDULA_RRHH_R, auth, rrhh_auth  # noqa: F401


async def test_solo_talento_humano(cliente, auth):
    assert (await cliente.get("/tablero/explorador", headers=auth)).status_code == 403
    r = await cliente.get("/tablero/explorar", headers=auth, params={"medida": "personas", "dimension": "sede"})
    assert r.status_code == 403


async def test_personas_por_sede_y_por_antiguedad(cliente, rrhh_auth, empleado):
    cat = (await cliente.get("/tablero/explorador", headers=rrhh_auth)).json()
    assert {"personas", "dias_gozados", "solicitudes"} <= {m["clave"] for m in cat["medidas"]}
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth,
                          params={"medida": "personas", "dimension": "sede"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] >= 1 and all(set(x) == {"etiqueta", "valor"} for x in d["datos"])
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth,
                          params={"medida": "personas", "dimension": "antiguedad"})
    assert any(x["etiqueta"] == "6 a 10 años" for x in r.json()["datos"])   # el empleado tiene 7


async def test_foto_de_hoy_no_se_reparte_por_mes(cliente, rrhh_auth):
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth,
                          params={"medida": "personas", "dimension": "mes"})
    assert r.status_code == 422
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth,
                          params={"medida": "altas", "dimension": "mes", "desde": "2020-01-01"})
    assert r.status_code == 200 and r.json()["periodo"]["desde"] == "2020-01-01"
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth,
                          params={"medida": "personas", "dimension": "nombre"})
    assert r.status_code == 422


async def test_vistas_propias_y_compartidas(cliente, rrhh_auth):
    r = await cliente.post("/tablero/vistas", headers=rrhh_auth, json={
        "nombre": "Saldo por área", "medida": "saldo_dias", "dimension": "area",
        "grafico": "barras", "filtros": {"sede": "sierra"}, "compartida": True})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    vistas = (await cliente.get("/tablero/vistas", headers=rrhh_auth)).json()
    v = next(x for x in vistas if x["id"] == vid)
    assert v["propia"] and v["filtros"] == {"sede": "sierra"}
    r = await cliente.patch(f"/tablero/vistas/{vid}", headers=rrhh_auth, json={"grafico": "tabla", "ancho": 2})
    assert r.status_code == 200
    r = await cliente.patch(f"/tablero/vistas/{vid}", headers=rrhh_auth, json={"dimension": "cedula"})
    assert r.status_code == 422
    assert (await cliente.delete(f"/tablero/vistas/{vid}", headers=rrhh_auth)).status_code == 200
    await ejecutar("delete from tablero_vistas where nombre = 'Saldo por área'")


async def test_bloque_de_cuota_de_discapacidad(cliente, rrhh_auth):
    r = await cliente.get("/tablero", headers=rrhh_auth)
    bloque = next(b for b in r.json()["bloques"] if b["clave"] == "cuota_discapacidad")
    assert {"requeridas", "faltan", "sustitutos"} <= set(bloque["detalle"])
