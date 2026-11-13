"""El departamento de Talento Humano: quiénes lo integran y a dónde le llega.

El sistema sabía quién tiene el ROL de Talento Humano, pero no tenía un
«departamento». Eso falla de dos formas que no producen ningún error:

  · Los avisos iban solo a buzones personales. La persona sale de
    vacaciones, cambia de puesto o deja la empresa, y las solicitudes
    siguen llegando a una dirección que nadie abre.
  · Quien deja el departamento y conserva el rol sigue viendo las fichas y
    las solicitudes de toda su región.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_RRHH_R, auth, rrhh_auth)  # noqa: F401

CEDULA_OTRO_RRHH = "0900000027"


@pytest.fixture(autouse=True)
async def buzones_como_estaban():
    """Devuelve los buzones del área a su valor original.

    Sin esto, una prueba que configura el buzón se lo deja puesto a las
    siguientes, y a partir de ahí los avisos al departamento salen con un
    destinatario de más. Costó encontrarlo una vez; no hace falta dos.
    """
    claves = ("rrhh_correo_sierra", "rrhh_correo_costa")
    antes = {c["clave"]: c["valor"] for c in await obtener_todos(
        "select clave, valor from public.app_config where clave = any(%s)", (list(claves),))}
    yield
    for clave, valor in antes.items():
        await ejecutar("update public.app_config set valor = %s where clave = %s",
                       (valor, clave))


@pytest.fixture
async def otro_de_rrhh():
    """Una segunda persona en Talento Humano, en la Sierra."""
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, region)
           values (%s, 'API Talento Dos', 'talento2@api.test', 'rrhh',
                   current_date - 1500, 'sierra')
           on conflict (cedula) do update set rol = 'rrhh', region = 'sierra'
           returning id""",
        (CEDULA_OTRO_RRHH,),
    )
    yield str(fila["id"])
    await ejecutar("delete from public.users where cedula = %s", (CEDULA_OTRO_RRHH,))


# ------------------------------------------------------------- la lista
async def test_la_lista_dice_quien_integra_el_departamento(cliente, rrhh_auth):
    r = await cliente.get("/admin/talento-humano", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "integrantes" in cuerpo and "correos" in cuerpo
    mia = next((p for p in cuerpo["integrantes"] if p["nombre"] == "API Talento"), None)
    assert mia is not None
    assert mia["region"] in ("sierra", "costa")
    assert "puede_recibir" in mia


async def test_marca_a_quien_no_puede_recibir_los_avisos(cliente, rrhh_auth):
    """Un correo de dominio inexistente no es un error: es un aviso perdido."""
    gente = (await cliente.get("/admin/talento-humano", headers=rrhh_auth)).json()["integrantes"]
    mia = next(p for p in gente if p["nombre"] == "API Talento")
    assert mia["puede_recibir"] is False, "talento@api.test no debería contar como válido"


async def test_un_empleado_no_ve_el_departamento(cliente, auth):
    assert (await cliente.get("/admin/talento-humano", headers=auth)).status_code == 403


# ------------------------------------------------------- el buzón del área
async def test_se_guarda_el_correo_del_departamento(cliente, rrhh_auth):
    r = await cliente.patch("/admin/talento-humano/correos", headers=rrhh_auth,
                            json={"sierra": "th.uio@itsanet.com.ec",
                                  "costa": "th.gye@itsanet.com.ec"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select public.rrhh_correo_de_region('costa') as buzon")
    assert fila["buzon"] == "th.gye@itsanet.com.ec"


async def test_se_puede_dejar_sin_buzon(cliente, rrhh_auth):
    """En blanco los avisos van solo a los correos personales, como antes."""
    await cliente.patch("/admin/talento-humano/correos", headers=rrhh_auth,
                        json={"sierra": "th.uio@itsanet.com.ec", "costa": ""})
    fila = await obtener_uno("select public.rrhh_correo_de_region('costa') as buzon")
    assert fila["buzon"] is None


async def test_una_direccion_mal_escrita_no_se_guarda(cliente, rrhh_auth):
    """Un buzón con una errata es igual de silencioso que no tener ninguno."""
    r = await cliente.patch("/admin/talento-humano/correos", headers=rrhh_auth,
                            json={"sierra": "talentohumano.itsanet.com.ec", "costa": ""})
    assert r.status_code == 422


async def test_un_empleado_no_cambia_el_buzon(cliente, auth):
    r = await cliente.patch("/admin/talento-humano/correos", headers=auth,
                            json={"sierra": "mio@itsanet.com.ec", "costa": ""})
    assert r.status_code == 403


# ------------------------------------------------------------- alta y baja
async def test_integrar_a_alguien_al_departamento(cliente, rrhh_auth, empleado):
    r = await cliente.post("/admin/talento-humano", headers=rrhh_auth,
                           json={"persona_id": empleado["id"], "region": "costa"})
    assert r.status_code == 201, r.text
    fila = await obtener_uno(
        "select rol::text as rol, region from public.users where id = %s", (empleado["id"],))
    assert fila["rol"] == "rrhh"
    assert fila["region"] == "costa"


async def test_a_un_administrador_no_se_le_baja_el_rol(cliente, rrhh_auth, empleado):
    """Integrarlo no debe quitarle atribuciones sin avisar."""
    await ejecutar("update public.users set rol = 'admin' where id = %s", (empleado["id"],))
    r = await cliente.post("/admin/talento-humano", headers=rrhh_auth,
                           json={"persona_id": empleado["id"], "region": "sierra"})
    assert r.status_code == 201, r.text
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (empleado["id"],))
    assert fila["rol"] == "admin"


async def test_retirar_a_alguien_le_quita_el_acceso_a_los_expedientes(
    cliente, rrhh_auth, otro_de_rrhh
):
    r = await cliente.post(f"/admin/talento-humano/{otro_de_rrhh}/retirar",
                           headers=rrhh_auth, json={"rol_destino": "empleado"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (otro_de_rrhh,))
    assert fila["rol"] == "empleado"


async def test_no_se_deja_una_region_sin_nadie(cliente, rrhh_auth, otro_de_rrhh):
    """Sin nadie en la región, sus solicitudes no le llegan a ninguna persona."""
    # Se deja a «API Talento Dos» como la única de la Costa.
    await ejecutar("update public.users set region = 'costa' where id = %s", (otro_de_rrhh,))
    r = await cliente.post(f"/admin/talento-humano/{otro_de_rrhh}/retirar",
                           headers=rrhh_auth, json={"rol_destino": "empleado"})
    assert r.status_code >= 400
    assert "única persona" in r.text or "unica persona" in r.text
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (otro_de_rrhh,))
    assert fila["rol"] == "rrhh", "la retiró pese a dejar la región vacía"


async def test_nadie_se_retira_a_si_mismo(cliente, rrhh_auth):
    yo = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_RRHH_R,))
    r = await cliente.post(f"/admin/talento-humano/{yo['id']}/retirar",
                           headers=rrhh_auth, json={"rol_destino": "empleado"})
    assert r.status_code >= 400
    assert "usted mismo" in r.text


async def test_el_rol_de_destino_no_puede_seguir_viendo_los_expedientes(
    cliente, rrhh_auth, otro_de_rrhh
):
    r = await cliente.post(f"/admin/talento-humano/{otro_de_rrhh}/retirar",
                           headers=rrhh_auth, json={"rol_destino": "admin"})
    assert r.status_code == 422, "admin no debería ser un destino válido"
