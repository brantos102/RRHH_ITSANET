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
    # El correo lo cambia la propia persona, pero no rige hasta que abre el
    # enlace que llega a la dirección nueva: no lo aprueba Talento Humano.
    assert niveles["email"] == "confirmado"
    assert niveles["cedula"] == "bloqueado"
    assert niveles["fecha_ingreso"] == "bloqueado"
    # El cargo y el jefe sí se pueden corregir, con confirmación: la planilla
    # los trajo mal en varios casos y antes no había forma de señalarlo.
    assert niveles["cargo"] == "revisado"
    assert niveles["jefe_id"] == "revisado"


async def test_el_telefono_se_corrige_al_instante(cliente, auth, empleado):
    r = await cliente.patch("/mi-ficha", headers=auth,
                            json={"telefono": "0987654321", "direccion": "Av. Amazonas 123"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select telefono, direccion from public.users where id = %s", (empleado["id"],))
    assert fila["telefono"] == "0987654321"
    assert fila["direccion"] == "Av. Amazonas 123"


async def test_el_correo_no_pasa_por_la_cola_de_revision(cliente, auth):
    """Nadie aprueba un buzón. Lo confirma el buzón mismo."""
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "email", "valor": "nuevo@itsanet.com.ec"})
    assert r.status_code == 422, r.text
    assert "enlace" in r.json()["detail"]["mensaje"]


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


async def test_confirmar_el_correo_habilita_el_acceso(cliente, auth, empleado):
    """Si el correo era un marcador, confirmarlo saca a la persona de la lista."""
    await ejecutar("update public.users set correo_pendiente = true where id = %s",
                   (empleado["id"],))
    r = await cliente.post("/mi-ficha/correo", headers=auth,
                           json={"email": "validado@itsanet.com.ec"})
    assert r.status_code == 202, r.text

    antes = await obtener_uno(
        "select email::text as email from public.users where id = %s", (empleado["id"],))
    assert antes["email"] != "validado@itsanet.com.ec", (
        "el correo no debe regir antes de confirmarse: un dedazo dejaría a la "
        "persona sin poder recibir ni el código de acceso ni el de confirmación"
    )

    token = await obtener_uno(
        """select token::text as token from public.confirmaciones_correo
            where user_id = %s and confirmado_en is null
            order by created_at desc limit 1""",
        (empleado["id"],))
    r = await cliente.post("/auth/confirmar-correo", json={"token": token["token"]})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select email::text as email, correo_pendiente from public.users where id = %s",
        (empleado["id"],))
    assert fila["email"] == "validado@itsanet.com.ec"
    assert fila["correo_pendiente"] is False


async def test_el_enlace_de_confirmacion_no_sirve_dos_veces(cliente, auth, empleado):
    await cliente.post("/mi-ficha/correo", headers=auth,
                       json={"email": "unavez@itsanet.com.ec"})
    token = await obtener_uno(
        """select token::text as token from public.confirmaciones_correo
            where user_id = %s and confirmado_en is null
            order by created_at desc limit 1""",
        (empleado["id"],))
    assert (await cliente.post("/auth/confirmar-correo",
                               json={"token": token["token"]})).status_code == 200
    repetido = await cliente.post("/auth/confirmar-correo", json={"token": token["token"]})
    assert repetido.status_code == 410


async def test_no_se_puede_reclamar_el_correo_de_otro(cliente, auth):
    """La dirección de otra persona no se toma ni pidiendo la confirmación."""
    ajeno = "1700000761"
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Otro Colaborador', 'ocupado@itsanet.com.ec', 'empleado',
                   current_date - 800)
           on conflict (cedula) do update set email = 'ocupado@itsanet.com.ec'
           returning id""",
        (ajeno,),
    )
    try:
        r = await cliente.post("/mi-ficha/correo", headers=auth,
                               json={"email": "ocupado@itsanet.com.ec"})
        assert r.status_code >= 400
        assert "otra persona" in str(r.json()).lower()
    finally:
        await ejecutar("delete from public.users where cedula = %s", (ajeno,))
