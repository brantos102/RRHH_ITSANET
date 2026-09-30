"""El expediente de una persona, y quién escribe las reglas que se leen.

Dos cosas que estaban repartidas o escritas en el código:

El expediente. Para responder «¿cuándo tomó vacaciones Fulano y qué tiene
pendiente?» había que abrir tres pantallas y cruzarlas a mano.

Los lineamientos. El recuadro «Antes de enviar, tenga presente» vivía dentro
del HTML, y son reglas que cambian por circular, no por versión del sistema.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)


async def test_buscar_encuentra_sin_tildes(cliente, rrhh_auth, empleado):
    """«Suarez» tiene que encontrar a «Suárez».

    Con trescientas cincuenta personas, un buscador que exige escribir el
    acento no lo usa nadie.
    """
    r = await cliente.get("/personas/buscar?q=suarez", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert any("Suárez" in p["nombre"] for p in r.json()), r.json()


async def test_buscar_por_los_primeros_digitos_de_la_cedula(cliente, rrhh_auth, empleado):
    """Nadie se sabe los diez dígitos de memoria; los primeros seis, sí."""
    r = await cliente.get(f"/personas/buscar?q={CEDULA_PRUEBA[:6]}", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert any(p["cedula"] == CEDULA_PRUEBA for p in r.json()), r.json()


async def test_una_sola_letra_no_devuelve_la_planilla(cliente, rrhh_auth):
    """Es un buscador de navegación, no un listado del personal."""
    assert (await cliente.get("/personas/buscar?q=a", headers=rrhh_auth)).json() == []


async def test_el_expediente_reune_lo_que_estaba_repartido(cliente, rrhh_auth, empleado):
    r = await cliente.get(f"/personas/{empleado['id']}", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for clave in ("persona", "devengo", "periodos", "solicitudes", "vacaciones", "resumen"):
        assert clave in cuerpo, clave
    assert cuerpo["persona"]["cedula"] == CEDULA_PRUEBA


async def test_un_jefe_solo_ve_a_su_gente(cliente, jefe_auth, rrhh_auth, empleado):
    """Y al probar el identificador de otra persona recibe lo mismo que si no
    existiera: no puede averiguar quién trabaja en otra área."""
    ajeno = await obtener_uno(
        """select id from public.users
            where activo and (jefe_id is null or jefe_id <> %s)
              and cedula <> %s limit 1""",
        (await _id_de(CEDULA_JEFE_R), CEDULA_PRUEBA))
    if ajeno is None:
        pytest.skip("no hay nadie fuera del equipo del jefe de prueba")

    r = await cliente.get(f"/personas/{ajeno['id']}", headers=jefe_auth)
    assert r.status_code == 404, r.text
    # Talento Humano sí lo ve: es su función.
    assert (await cliente.get(f"/personas/{ajeno['id']}", headers=rrhh_auth)).status_code == 200


async def test_un_companero_no_abre_el_expediente_de_otro(cliente, auth, empleado):
    """LOPDP Art. 10: nadie accede a datos que no le corresponden."""
    assert (await cliente.get(f"/personas/{empleado['id']}",
                              headers=auth)).status_code == 403
    assert (await cliente.get("/personas/buscar?q=suarez", headers=auth)).status_code == 403


async def test_sin_sesion_no_hay_expediente(cliente, empleado):
    assert (await cliente.get(f"/personas/{empleado['id']}")).status_code == 401


async def _id_de(cedula: str):
    fila = await obtener_uno("select id from public.users where cedula = %s", (cedula,))
    return fila["id"] if fila else None


# ------------------------------------------------------------- lineamientos

async def test_los_lineamientos_llegan_al_formulario(cliente, auth):
    """Lo que el colaborador lee antes de enviar sale de la base, no del HTML."""
    r = await cliente.get("/catalogos/antiguedad", headers=auth)
    assert r.status_code == 200, r.text
    avisos = r.json()["avisos"]
    assert avisos, "el formulario se quedó sin lineamientos"
    assert {a["ambito"] for a in avisos} <= {"vacacion", "permiso", "ambos"}


async def test_talento_humano_los_escribe(cliente, auth, rrhh_auth):
    creado = await cliente.post("/rrhh/lineamientos", headers=rrhh_auth, json={
        "texto": "Las vacaciones de diciembre se piden hasta el 15 de noviembre.",
        "ambito": "vacacion"})
    assert creado.status_code == 201, creado.text
    try:
        textos = [a["texto"] for a in
                  (await cliente.get("/catalogos/antiguedad", headers=auth)).json()["avisos"]]
        assert any("15 de noviembre" in t for t in textos)
    finally:
        await ejecutar("delete from public.lineamientos_solicitud where id = %s",
                       (creado.json()["id"],))


async def test_apagar_uno_lo_quita_del_formulario(cliente, auth, rrhh_auth):
    creado = await cliente.post("/rrhh/lineamientos", headers=rrhh_auth, json={
        "texto": "Regla temporal que se va a apagar en esta prueba.", "ambito": "permiso"})
    ident = creado.json()["id"]
    try:
        r = await cliente.patch(f"/rrhh/lineamientos/{ident}",
                                headers=rrhh_auth, json={"activo": False})
        assert r.status_code == 200, r.text
        textos = [a["texto"] for a in
                  (await cliente.get("/catalogos/antiguedad", headers=auth)).json()["avisos"]]
        assert not any("se va a apagar" in t for t in textos)
    finally:
        await ejecutar("delete from public.lineamientos_solicitud where id = %s", (ident,))


async def test_un_lineamiento_vacio_se_rechaza(cliente, rrhh_auth):
    r = await cliente.post("/rrhh/lineamientos", headers=rrhh_auth, json={"texto": "  "})
    assert r.status_code == 422, r.text


async def test_solo_talento_humano_los_cambia(cliente, auth, jefe_auth):
    """Un jefe aplica las reglas de la empresa; no las escribe."""
    for cabeceras in (auth, jefe_auth):
        assert (await cliente.get("/rrhh/lineamientos",
                                  headers=cabeceras)).status_code == 403
        assert (await cliente.post("/rrhh/lineamientos", headers=cabeceras,
                                   json={"texto": "Regla puesta por quien no debe."})
                ).status_code == 403
