"""Chat entre el colaborador y Talento Humano.

Lo que más importa probar no es que los mensajes lleguen, sino quién NO
puede leerlos: si un jefe pudiera ver lo que su gente consulta, nadie
volvería a consultar nada.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CED_RRHH_C = "1700000019"
CED_JEFE_C = "1700000027"


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await ejecutar("update public.users set ciudad = 'Quito' where id = %s", (empleado["id"],))
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Talento Chat', 'chatrrhh@api.test', 'rrhh', current_date - 900, 'Quito')
           on conflict (cedula) do update set rol='rrhh', ciudad='Quito' returning id""",
        (CED_RRHH_C,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_C})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_C, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_RRHH_C,))


@pytest.fixture
async def jefe_auth(cliente, codigos, empleado):
    jefe = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Jefe Curioso', 'jefechat@api.test', 'jefe', current_date - 900, 'Quito')
           on conflict (cedula) do update set rol='jefe' returning id""", (CED_JEFE_C,))
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (jefe["id"], empleado["id"]))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_JEFE_C})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_JEFE_C, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_JEFE_C,))


async def test_escribir_abre_la_conversacion(cliente, auth):
    r = await cliente.post("/chat/mensajes", headers=auth, json={
        "texto": "Buenos días, ¿cuántos días de vacaciones me quedan?",
        "asunto": "Consulta de saldo",
    })
    assert r.status_code == 201, r.text
    assert r.json()["conversacion_id"]


async def test_llega_a_la_bandeja_de_su_region(cliente, auth, rrhh_auth):
    creada = await cliente.post("/chat/mensajes", headers=auth,
                                json={"texto": "¿Por qué me rechazaron la solicitud?"})
    bandeja = await cliente.get("/chat/bandeja", headers=rrhh_auth)
    assert bandeja.status_code == 200, bandeja.text
    ids = {c["id"] for c in bandeja.json()}
    assert creada.json()["conversacion_id"] in ids


async def test_talento_humano_responde_y_queda_anotado(cliente, auth, rrhh_auth):
    creada = await cliente.post("/chat/mensajes", headers=auth,
                                json={"texto": "Tengo una duda con mi permiso"})
    cid = creada.json()["conversacion_id"]

    r = await cliente.post("/chat/mensajes", headers=rrhh_auth,
                           json={"conversacion_id": cid, "texto": "Con gusto, reviso y le digo"})
    assert r.status_code == 201, r.text

    hilo = await cliente.get(f"/chat/conversaciones/{cid}", headers=auth)
    textos = [m["texto"] for m in hilo.json()["mensajes"]]
    assert len(textos) == 2
    assert hilo.json()["mensajes"][-1]["es_rrhh"] is True

    fila = await obtener_uno(
        "select atendida_por from public.conversaciones where id = %s", (cid,))
    assert fila["atendida_por"] is not None


async def test_el_jefe_no_puede_leer_lo_que_su_gente_consulta(
        cliente, auth, jefe_auth):
    """Si pudiera, nadie volvería a preguntar nada."""
    creada = await cliente.post("/chat/mensajes", headers=auth,
                                json={"texto": "Quiero consultar algo reservado"})
    cid = creada.json()["conversacion_id"]
    r = await cliente.get(f"/chat/conversaciones/{cid}", headers=jefe_auth)
    assert r.status_code == 403


async def test_talento_humano_no_inicia_conversaciones(cliente, rrhh_auth):
    """El canal es para consultar, no para que Talento Humano interpele."""
    r = await cliente.post("/chat/mensajes", headers=rrhh_auth,
                           json={"texto": "Necesito hablar con usted"})
    assert r.status_code == 422


async def test_cerrar_y_reabrir(cliente, auth, rrhh_auth):
    creada = await cliente.post("/chat/mensajes", headers=auth, json={"texto": "Una consulta"})
    cid = creada.json()["conversacion_id"]
    await cliente.post(f"/chat/conversaciones/{cid}/cerrar", headers=rrhh_auth)

    fila = await obtener_uno("select estado from public.conversaciones where id = %s", (cid,))
    assert fila["estado"] == "cerrada"

    # Si la persona vuelve a escribir, se reabre sola
    await cliente.post("/chat/mensajes", headers=auth,
                       json={"conversacion_id": cid, "texto": "Sigo con la duda"})
    fila = await obtener_uno("select estado from public.conversaciones where id = %s", (cid,))
    assert fila["estado"] == "abierta"


async def test_los_contactos_son_los_de_su_region(cliente, auth, rrhh_auth):
    r = await cliente.get("/chat/contactos", headers=auth)
    assert r.status_code == 200
    assert r.json()["sede"] == "Quito"
    assert any(p["nombre"] == "Talento Chat" for p in r.json()["equipo"])
