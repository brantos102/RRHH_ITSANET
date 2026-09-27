"""Ficha personal: qué corrige la persona y qué valida Talento Humano."""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CED_RRHH_F = "1700000019"


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Talento Ficha', 'ficharrhh@api.test', 'rrhh', current_date - 900, 'Quito')
           on conflict (cedula) do update set rol = 'rrhh' returning id""", (CED_RRHH_F,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_F})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_F, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_RRHH_F,))


async def test_la_ficha_dice_que_se_puede_tocar_y_que_no(cliente, auth):
    r = await cliente.get("/mi-ficha", headers=auth)
    assert r.status_code == 200, r.text
    niveles = {c["campo"]: c["nivel"] for c in r.json()["campos"]}
    assert niveles["telefono"] == "libre"
    assert niveles["email"] == "revisado"
    assert niveles["cedula"] == "bloqueado"
    assert niveles["fecha_ingreso"] == "bloqueado"


async def test_el_telefono_se_corrige_al_instante(cliente, auth, empleado):
    r = await cliente.patch("/mi-ficha", headers=auth,
                            json={"telefono": "0987654321", "direccion": "Av. Amazonas 123"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select telefono, direccion from public.users where id = %s", (empleado["id"],))
    assert fila["telefono"] == "0987654321"
    assert fila["direccion"] == "Av. Amazonas 123"


async def test_el_correo_no_se_cambia_solo(cliente, auth):
    """De ahí salen los códigos de acceso: lo valida Talento Humano."""
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "email", "valor": "nuevo@itsanet.com.ec"})
    assert r.status_code == 201, r.text
    assert "revisará" in r.json()["mensaje"]


async def test_la_fecha_de_ingreso_no_se_toca(cliente, auth):
    """De ella dependen los días de vacaciones: no es dato del interesado."""
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "fecha_ingreso", "valor": "2015-01-01"})
    assert r.status_code == 422
    assert "no se modifica" in r.json()["detail"]["mensaje"]


async def test_la_cedula_tampoco(cliente, auth):
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "cedula", "valor": "1710034065"})
    assert r.status_code == 422


async def test_un_campo_inventado_se_rechaza(cliente, auth):
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "dias_vacaciones_falsos", "valor": "999"})
    assert r.status_code == 422


async def test_talento_humano_aprueba_y_el_dato_rige(cliente, auth, rrhh_auth, empleado):
    pedido = await cliente.post("/mi-ficha/cambios", headers=auth,
                                json={"campo": "nombre", "valor": "Ana María Suárez"})
    cambio_id = pedido.json()["id"]

    bandeja = await cliente.get("/rrhh/cambios-ficha", headers=rrhh_auth)
    assert cambio_id in {c["id"] for c in bandeja.json()}

    r = await cliente.post(f"/rrhh/cambios-ficha/{cambio_id}", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("select nombre from public.users where id = %s", (empleado["id"],))
    assert fila["nombre"] == "Ana María Suárez"


async def test_rechazar_exige_decir_por_que(cliente, auth, rrhh_auth):
    pedido = await cliente.post("/mi-ficha/cambios", headers=auth,
                                json={"campo": "nombre", "valor": "Nombre Inventado"})
    r = await cliente.post(f"/rrhh/cambios-ficha/{pedido.json()['id']}", headers=rrhh_auth,
                           json={"accion": "rechazar"})
    assert r.status_code == 422


async def test_aprobar_el_correo_habilita_el_acceso(cliente, auth, rrhh_auth, empleado):
    """Si el correo era un marcador, validarlo saca a la persona de la lista."""
    await ejecutar("update public.users set correo_pendiente = true where id = %s",
                   (empleado["id"],))
    pedido = await cliente.post("/mi-ficha/cambios", headers=auth,
                                json={"campo": "email", "valor": "validado@itsanet.com.ec"})
    await cliente.post(f"/rrhh/cambios-ficha/{pedido.json()['id']}", headers=rrhh_auth,
                       json={"accion": "aprobar"})
    fila = await obtener_uno(
        "select email::text as email, correo_pendiente from public.users where id = %s",
        (empleado["id"],))
    assert fila["email"] == "validado@itsanet.com.ec"
    assert fila["correo_pendiente"] is False
