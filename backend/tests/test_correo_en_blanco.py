"""Quien no tiene correo no tiene correo, y el sistema lo dice así.

La columna era `not null` con formato obligatorio, así que la carga de la
planilla no tenía más remedio que inventar una dirección para las 225
personas que llegaron sin ella: «0927127886@pendiente.itsanet.local». El
dominio no existe, el código de acceso se enviaba a la nada, y el formulario
de primer ingreso mostraba esa dirección falsa como si fuera un dato de la
persona.

Los correos aquí son personales, no institucionales. La empresa no puede
fabricarlos: los registra cada quien cuando entra.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno

CED_SIN = "1700000050"


@pytest.fixture
async def sin_correo(empleado):
    fila = await obtener_uno(
        """insert into public.users
             (cedula, nombre, email, rol, fecha_ingreso, fecha_nacimiento,
              correo_pendiente, ficha_completa, ciudad)
           values (%s, 'Sin Correo Real', null, 'empleado', current_date - 900,
                   '1990-05-20', true, false, 'Quito')
           on conflict (cedula) do update
             set email = null, correo_pendiente = true, ficha_completa = false
           returning id""",
        (CED_SIN,),
    )
    yield {"id": str(fila["id"]), "cedula": CED_SIN}
    await ejecutar("delete from public.users where cedula = %s", (CED_SIN,))


async def test_se_puede_guardar_a_alguien_sin_correo(sin_correo):
    fila = await obtener_uno(
        "select email from public.users where cedula = %s", (CED_SIN,))
    assert fila["email"] is None, "el campo debe admitir «no sabemos»"


async def test_una_direccion_mal_formada_sigue_rechazandose(sin_correo):
    """Admitir nulo no es admitir cualquier cosa."""
    with pytest.raises(Exception) as fallo:
        await ejecutar(
            "update public.users set email = 'esto no es un correo' where cedula = %s",
            (CED_SIN,))
    assert "users_email_formato" in str(fallo.value)


async def test_no_queda_ninguna_direccion_inventada():
    filas = await obtener_todos(
        """select cedula from public.users
            where email::text like '%%@pendiente.itsanet.local'""")
    assert not filas, f"quedan direcciones inventadas: {[f['cedula'] for f in filas]}"


async def test_el_alta_guiada_alcanza_a_quien_no_tiene_correo(cliente, sin_correo):
    """Es el caso nuevo: antes todos tenían algo, aunque fuera inventado."""
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": CED_SIN})
    assert r.status_code == 200, r.text
    assert r.json()["necesita"] is True, (
        "quien no tiene correo tiene que poder registrarlo desde la pantalla de acceso"
    )


async def test_pedir_el_codigo_sin_correo_no_revienta(cliente, sin_correo):
    """Y si alguien lo intenta igual, se le responde, no se cae el servidor."""
    r = await cliente.post("/auth/solicitar-token", json={"cedula": CED_SIN})
    assert r.status_code < 500, r.text


async def test_la_lista_de_pendientes_dice_a_quien_le_alcanza_el_alta(sin_correo):
    fila = await obtener_uno(
        "select puede_probar_identidad from public.v_sin_correo where cedula = %s",
        (CED_SIN,))
    assert fila is not None, "debería figurar entre quienes no tienen correo"
    assert fila["puede_probar_identidad"] is True, (
        "tiene fecha de nacimiento y de ingreso: el alta guiada le alcanza"
    )


async def test_quien_no_tiene_fecha_de_nacimiento_queda_señalado(sin_correo):
    """Sin ese dato el alta guiada no le sirve y Talento Humano debe saberlo."""
    await ejecutar(
        "update public.users set fecha_nacimiento = null where cedula = %s", (CED_SIN,))
    fila = await obtener_uno(
        "select puede_probar_identidad from public.v_sin_correo where cedula = %s",
        (CED_SIN,))
    assert fila["puede_probar_identidad"] is False
