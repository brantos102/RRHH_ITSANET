"""Nadie se cambia a sí mismo la fecha de ingreso, la cédula ni el saldo.

Son los datos de los que dependen los días de vacaciones y la identidad de la
persona: si el empleado pudiera tocarlos, podría fabricarse antigüedad. Se
comprueba por todas las vías, no solo por la que usa el formulario: la
protección tiene que estar en la base, porque el backend entra con
credenciales de servicio y un cliente alterado no pasa por el formulario.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

# Los que solo maneja Talento Humano, con el valor que un atacante pondría.
BLOQUEADOS = {
    "fecha_ingreso": "2000-01-01",      # más antigüedad = más días
    "cedula": "1710034065",             # suplantar a otra persona
    "dias_vacaciones": "365",           # saldo a voluntad
    "cargo": "Gerente General",
    "departamento": "GERENCIA",
    "jefe_id": None,                    # quedarse sin quien lo autorice
}


@pytest.fixture
async def auth_empleado(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --------------------------------------------------------- por la vía directa
@pytest.mark.parametrize("campo", [c for c in BLOQUEADOS if c != "jefe_id"])
async def test_no_se_corrigen_directamente(cliente, auth_empleado, empleado, campo):
    """`/mi-ficha` acepta una lista cerrada de campos; el resto ni se mira.

    Se comprueba sobre el dato y no sobre el código de respuesta: el modelo
    descarta en silencio lo que no reconoce, así que un 422 podría significar
    «campo rechazado» o «no mandó nada», y confundir las dos cosas deja la
    prueba pasando aunque la protección desaparezca.
    """
    antes = await obtener_uno(
        f"select {campo}::text as v from public.users where id = %s", (empleado["id"],))

    await cliente.patch("/mi-ficha", headers=auth_empleado,
                        json={campo: BLOQUEADOS[campo]})

    despues = await obtener_uno(
        f"select {campo}::text as v from public.users where id = %s", (empleado["id"],))
    assert despues["v"] == antes["v"], f"{campo} cambió y no debía"


@pytest.mark.parametrize("campo", [c for c in BLOQUEADOS if c != "jefe_id"])
async def test_no_se_piden_ni_por_revision(cliente, auth_empleado, campo):
    """Tampoco por la vía de «lo revisa Talento Humano»: no son revisables."""
    r = await cliente.post("/mi-ficha/cambios", headers=auth_empleado,
                           json={"campo": campo, "valor": str(BLOQUEADOS[campo]),
                                 "motivo": "Intento deliberado de cambiar un dato bloqueado"})
    assert r.status_code in (403, 422), f"{campo}: {r.status_code} {r.text}"
    assert "Talento Humano" in r.text or "no se modifica" in r.text, r.text


async def test_la_base_rechaza_el_campo_aunque_el_backend_lo_dejara_pasar(empleado):
    """La última línea es la base, no el formulario ni el modelo de la API.

    El backend entra con credenciales de servicio y no pasa por las políticas
    de la base, así que si alguien añadiera `fecha_ingreso` al modelo de la
    API por descuido, esto es lo único que seguiría frenándolo.
    """
    with pytest.raises(Exception) as fallo:
        await obtener_uno(
            "select public.actualizar_ficha_libre(%s, %s::jsonb)",
            (empleado["id"], '{"fecha_ingreso": "2000-01-01"}'),
        )
    assert "Talento Humano" in str(fallo.value) or "no se corrige" in str(fallo.value)

    intacta = await obtener_uno(
        "select fecha_ingreso from public.users where id = %s", (empleado["id"],))
    assert intacta["fecha_ingreso"] != date(2000, 1, 1)


async def test_la_fecha_de_ingreso_no_cambia_por_ninguna_via(cliente, auth_empleado, empleado):
    """La comprobación que importa: el dato sigue igual después de intentarlo."""
    antes = (await obtener_uno(
        "select fecha_ingreso from public.users where id = %s", (empleado["id"],)))["fecha_ingreso"]

    await cliente.patch("/mi-ficha", headers=auth_empleado,
                        json={"fecha_ingreso": "2000-01-01"})
    await cliente.post("/mi-ficha/cambios", headers=auth_empleado,
                       json={"campo": "fecha_ingreso", "valor": "2000-01-01",
                             "motivo": "Intento por la via de revision de Talento Humano"})
    # Mezclado con un campo legítimo, por si la validación se detuviera en el primero.
    await cliente.patch("/mi-ficha", headers=auth_empleado,
                        json={"telefono": "0999888777", "fecha_ingreso": "2000-01-01"})

    despues = (await obtener_uno(
        "select fecha_ingreso from public.users where id = %s", (empleado["id"],)))["fecha_ingreso"]
    assert despues == antes, "la fecha de ingreso cambió: de ella dependen los días"


async def test_un_campo_bloqueado_no_cuela_junto_a_uno_valido(cliente, auth_empleado, empleado):
    """El campo legítimo se aplica; el prohibido se descarta sin tocar nada."""
    r = await cliente.patch("/mi-ficha", headers=auth_empleado,
                            json={"telefono": "0988777666", "dias_vacaciones": 365})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select telefono, dias_vacaciones from public.users where id = %s", (empleado["id"],))
    assert fila["telefono"] == "0988777666", "el campo válido sí debía aplicarse"
    assert float(fila["dias_vacaciones"]) != 365, "el saldo no se toca desde la ficha"


# --------------------------------------------------------------- lo permitido
async def test_lo_suyo_si_lo_cambia_solo(cliente, auth_empleado, empleado):
    """Teléfono, emergencia, dirección y foto: sin trámite."""
    r = await cliente.patch("/mi-ficha", headers=auth_empleado, json={
        "telefono": "0991234567",
        "telefono_alternativo": "0987654321",
        "direccion": "Av. Amazonas y Naciones Unidas, Quito",
    })
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select telefono, telefono_alternativo, direccion from public.users where id = %s",
        (empleado["id"],))
    assert fila["telefono"] == "0991234567"
    assert fila["direccion"].startswith("Av. Amazonas")


async def test_lo_delicado_pasa_por_revision(cliente, auth_empleado, empleado):
    """El nombre o el correo cambian, pero los confirma Talento Humano."""
    r = await cliente.post("/mi-ficha/cambios", headers=auth_empleado, json={
        "campo": "estado_civil", "valor": "casado",
        "motivo": "Me case el mes pasado y adjunto el acta de matrimonio"})
    assert r.status_code in (200, 201), r.text

    pendientes = await obtener_todos(
        "select campo, estado from public.cambios_ficha where user_id = %s and estado = 'pendiente'",
        (empleado["id"],))
    assert any(p["campo"] == "estado_civil" for p in pendientes)

    # Y no se aplicó todavía: eso es lo que significa «pendiente».
    actual = await obtener_uno(
        "select estado_civil from public.users where id = %s", (empleado["id"],))
    assert actual["estado_civil"] != "casado", "no debe aplicarse antes de aprobarse"


async def test_el_catalogo_declara_bloqueados_los_que_debe(cliente, auth_empleado):
    """Si alguien reclasifica un campo, esta prueba lo delata."""
    filas = await obtener_todos(
        "select campo from public.campos_ficha where nivel = 'bloqueado'")
    bloqueados = {f["campo"] for f in filas}
    for campo in ("fecha_ingreso", "cedula", "dias_vacaciones", "cargo",
                  "departamento", "jefe_id"):
        assert campo in bloqueados, f"{campo} debe estar bloqueado para el empleado"
