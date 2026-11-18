"""Ficha personal: qué corrige la persona y qué valida Talento Humano."""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.conftest import Sql, persona

CED_RRHH_F = "1700000019"


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await persona(CED_RRHH_F, al_existir={"rol": 'rrhh'}, nombre='Talento Ficha', email='ficharrhh@api.test', rol='rrhh', fecha_ingreso=Sql("current_date() - interval 900 day"), ciudad='Quito')
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_F})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_F, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from users where cedula = %s", (CED_RRHH_F,))


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
    # El jefe se puede señalar, con confirmación. El cargo y el área, desde
    # la 0016, los administra Talento Humano: se declaran solo al entrar por
    # primera vez si no constaban.
    assert niveles["cargo"] == "bloqueado" and niveles["departamento"] == "bloqueado"
    assert niveles["jefe_id"] == "revisado"


async def test_el_telefono_se_corrige_al_instante(cliente, auth, empleado):
    r = await cliente.patch("/mi-ficha", headers=auth,
                            json={"telefono": "0987654321", "direccion": "Av. Amazonas 123"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select telefono, direccion from users where id = %s", (empleado["id"],))
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
    fila = await obtener_uno("select nombre from users where id = %s", (empleado["id"],))
    assert fila["nombre"] == "Ana María Suárez"


async def test_rechazar_exige_decir_por_que(cliente, auth, rrhh_auth):
    pedido = await cliente.post("/mi-ficha/cambios", headers=auth,
                                json={"campo": "nombre", "valor": "Nombre Inventado"})
    r = await cliente.post(f"/rrhh/cambios-ficha/{pedido.json()['id']}", headers=rrhh_auth,
                           json={"accion": "rechazar"})
    assert r.status_code == 422


async def test_confirmar_el_correo_habilita_el_acceso(cliente, auth, empleado):
    """Si el correo era un marcador, confirmarlo saca a la persona de la lista."""
    await ejecutar("update users set correo_pendiente = true where id = %s",
                   (empleado["id"],))
    r = await cliente.post("/mi-ficha/correo", headers=auth,
                           json={"email": "validado@itsanet.com.ec"})
    assert r.status_code == 202, r.text

    antes = await obtener_uno(
        "select email as email from users where id = %s", (empleado["id"],))
    assert antes["email"] != "validado@itsanet.com.ec", (
        "el correo no debe regir antes de confirmarse: un dedazo dejaría a la "
        "persona sin poder recibir ni el código de acceso ni el de confirmación"
    )

    token = await obtener_uno(
        """select token as token from confirmaciones_correo
            where user_id = %s and confirmado_en is null
            order by created_at desc limit 1""",
        (empleado["id"],))
    r = await cliente.post("/auth/confirmar-correo", json={"token": str(token["token"])})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select email as email, correo_pendiente from users where id = %s",
        (empleado["id"],))
    assert fila["email"] == "validado@itsanet.com.ec"
    assert fila["correo_pendiente"] is False


async def test_el_enlace_de_confirmacion_no_sirve_dos_veces(cliente, auth, empleado):
    await cliente.post("/mi-ficha/correo", headers=auth,
                       json={"email": "unavez@itsanet.com.ec"})
    token = await obtener_uno(
        """select token as token from confirmaciones_correo
            where user_id = %s and confirmado_en is null
            order by created_at desc limit 1""",
        (empleado["id"],))
    assert (await cliente.post("/auth/confirmar-correo",
                               json={"token": str(token["token"])})).status_code == 200
    repetido = await cliente.post("/auth/confirmar-correo", json={"token": str(token["token"])})
    assert repetido.status_code == 410


async def test_no_se_puede_reclamar_el_correo_de_otro(cliente, auth):
    """La dirección de otra persona no se toma ni pidiendo la confirmación."""
    ajeno = "1700000761"
    await persona(ajeno, al_existir={"email": 'ocupado@itsanet.com.ec'}, nombre='Otro Colaborador', email='ocupado@itsanet.com.ec', rol='empleado', fecha_ingreso=Sql("current_date() - interval 800 day"))
    try:
        r = await cliente.post("/mi-ficha/correo", headers=auth,
                               json={"email": "ocupado@itsanet.com.ec"})
        assert r.status_code >= 400
        assert "otra persona" in str(r.json()).lower()
    finally:
        await ejecutar("delete from users where cedula = %s", (ajeno,))


# ------------------------------------------- Talento Humano se entera
async def test_un_pedido_desde_mi_ficha_avisa_a_talento_humano(cliente, auth, empleado, monkeypatch):
    """Antes quedaba guardado sin avisar a nadie."""
    from app import notificaciones
    from app.db import ejecutar as _ejecutar, obtener_todos as _todos
    correos: list = []

    async def falso(destinos, nombre, cedula, pedidos):
        correos.append(pedidos)

    monkeypatch.setattr(notificaciones, "avisar_correccion_de_ficha", falso)
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "estado_civil", "valor": "casado"})
    assert r.status_code == 201, r.text
    assert correos == [[("Estado civil", "casado")]]
    avisos = await _todos("select user_id, accion_url from notifications "
                          "where entidad = 'cambios_ficha' and entidad_id = %s", (empleado["id"],))
    assert avisos and all(a["accion_url"].startswith("administracion.html?atender=persona:") for a in avisos)
    await _ejecutar("delete from notifications where entidad = 'cambios_ficha' and entidad_id = %s",
                    (empleado["id"],))


# ---------------------------------------- contactos de emergencia y sede
async def test_mis_contactos_se_ven_y_se_corrigen(cliente, auth, empleado):
    r = await cliente.post("/mi-ficha/contactos", headers=auth, json={
        "nombre": "Contacto Inventado", "parentesco": "madre", "telefono": "099 111 2224"})
    assert r.status_code == 201, r.text
    contactos = r.json()["contactos"]
    assert len(contactos) == 1 and contactos[0]["es_principal"] and contactos[0]["telefono"] == "0991112224"
    cid = contactos[0]["id"]
    r = await cliente.post("/mi-ficha/contactos", headers=auth, json={
        "nombre": "Otro Contacto", "parentesco": "hermano", "telefono": "0991112225",
        "es_principal": True})
    principal = [c for c in r.json()["contactos"] if c["es_principal"]]
    assert len(principal) == 1 and principal[0]["nombre"] == "Otro Contacto"
    r = await cliente.delete(f"/mi-ficha/contactos/{principal[0]['id']}", headers=auth)
    queda = r.json()["contactos"]
    assert len(queda) == 1 and queda[0]["id"] == cid and queda[0]["es_principal"], \
        "siempre queda uno principal"
    await ejecutar("delete from emergency_contacts where user_id = %s", (empleado["id"],))


async def test_no_se_toca_el_contacto_de_otra_persona(cliente, auth, empleado):
    otro = await obtener_uno("select id from emergency_contacts where user_id <> %s limit 1",
                             (empleado["id"],))
    if otro:
        r = await cliente.patch(f"/mi-ficha/contactos/{otro['id']}", headers=auth, json={
            "nombre": "Intruso Intento", "telefono": "0990000000"})
        assert r.status_code == 404


async def test_talento_humano_cambia_la_sede_y_lo_pendiente_se_va_con_ella(
        cliente, rrhh_auth, empleado):
    await ejecutar("update users set ciudad = 'Guayaquil' where id = %s", (empleado["id"],))
    fila = await obtener_uno("select region from users where id = %s", (empleado["id"],))
    assert fila["region"] == "costa"
    from app.db import nuevo_id
    rid = str(nuevo_id())
    await ejecutar(
        """insert into requests (id, user_id, tipo, estado, fecha_inicio, fecha_fin,
                                 dias_solicitados, descripcion, justificacion, region)
           values (%s, %s, 'vacacion', 'pendiente_rrhh', current_date() + interval 40 day,
                   current_date() + interval 46 day, 5, 'Prueba de traslado de sede',
                   'Justificación de la prueba de traslado', 'costa')""",
        (rid, empleado["id"]))
    try:
        r = await cliente.patch(f"/admin/usuarios/{empleado['id']}", headers=rrhh_auth,
                                json={"region": "sierra"})
        assert r.status_code == 200, r.text
        assert "Quito" in r.json()["mensaje"] and "1 solicitud" in r.json()["mensaje"]
        u = await obtener_uno("select region, ciudad from users where id = %s", (empleado["id"],))
        assert u["region"] == "sierra" and u["ciudad"] == "Quito", "ciudad y sede no se contradicen"
        sol = await obtener_uno("select region from requests where id = %s", (rid,))
        assert sol["region"] == "sierra"
    finally:
        await ejecutar("delete from requests where id = %s", (rid,))
