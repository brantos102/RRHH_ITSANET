"""Alta guiada de quien no tiene correo registrado.

230 de 351 personas llegaron sin correo y el acceso es por código al
correo. Estas pruebas fijan las tres barreras que impiden que la vía se
convierta en una forma de apropiarse de una cuenta ajena conociendo solo
una cédula, que en Ecuador es un dato casi público.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno

CED_SIN_CORREO = "1700000019"
NACIMIENTO = "1990-03-15"
INGRESO = "2022-06-01"


@pytest.fixture
async def sin_correo(empleado):
    fila = await obtener_uno(
        """insert into public.users
             (cedula, nombre, email, rol, fecha_ingreso, fecha_nacimiento,
              correo_pendiente, ficha_completa, ciudad)
           values (%s, 'Sin Correo Prueba', %s, 'empleado', %s, %s, true, false, 'Quito')
           on conflict (cedula) do update
             set correo_pendiente = true, ficha_completa = false,
                 fecha_nacimiento = excluded.fecha_nacimiento,
                 fecha_ingreso = excluded.fecha_ingreso
           returning id""",
        (CED_SIN_CORREO, f"{CED_SIN_CORREO}@pendiente.itsanet.local", INGRESO, NACIMIENTO),
    )
    yield {"id": str(fila["id"]), "cedula": CED_SIN_CORREO}
    await ejecutar("delete from public.users where cedula = any(%s)",
                   ([CED_SIN_CORREO, "1700000027"],))


async def test_se_detecta_a_quien_debe_completar_su_ficha(cliente, sin_correo):
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": CED_SIN_CORREO})
    assert r.status_code == 200 and r.json()["necesita"] is True


async def test_quien_ya_tiene_correo_no_pasa_por_ahi(cliente, empleado):
    """La vía no sirve para apropiarse de una cuenta que ya funciona."""
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": empleado["cedula"]})
    assert r.json()["necesita"] is False


async def test_una_cedula_inexistente_responde_lo_mismo(cliente):
    """No se revela qué cédulas están registradas."""
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": "1710034065"})
    assert r.status_code == 200 and r.json()["necesita"] is False


async def test_conocer_la_cedula_no_basta(cliente, sin_correo):
    r = await cliente.post("/auth/probar-identidad", json={
        "cedula": CED_SIN_CORREO,
        "fecha_nacimiento": "1985-01-01", "fecha_ingreso": "2020-01-01",
    })
    assert r.status_code == 404


async def test_con_los_dos_datos_del_expediente_se_habilita(cliente, sin_correo):
    r = await cliente.post("/auth/probar-identidad", json={
        "cedula": CED_SIN_CORREO,
        "fecha_nacimiento": NACIMIENTO, "fecha_ingreso": INGRESO,
    })
    assert r.status_code == 200, r.text
    assert r.json()["token"]
    assert r.json()["nombre"] == "Sin Correo Prueba"


async def test_la_ficha_queda_registrada_y_la_persona_puede_entrar(
        cliente, codigos, sin_correo):
    prueba = await cliente.post("/auth/probar-identidad", json={
        "cedula": CED_SIN_CORREO,
        "fecha_nacimiento": NACIMIENTO, "fecha_ingreso": INGRESO,
    })
    r = await cliente.post("/auth/completar-ficha", json={
        "token": prueba.json()["token"],
        "email": "sincorreo@itsanet.com.ec",
        "telefono": "0991112223",
        "emergencia_nombre": "Contacto Prueba",
        "emergencia_parentesco": "madre",
        "emergencia_telefono": "0994445556",
    })
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        """select email::text as email, correo_pendiente, telefono, ficha_completa
             from public.users where cedula = %s""", (CED_SIN_CORREO,))
    assert fila["email"] == "sincorreo@itsanet.com.ec"
    assert fila["correo_pendiente"] is False
    assert fila["telefono"] == "0991112223"
    assert fila["ficha_completa"] is True

    contacto = await obtener_uno(
        """select nombre, parentesco::text as parentesco from public.emergency_contacts
            where user_id = %s""", (sin_correo["id"],))
    assert contacto["nombre"] == "Contacto Prueba"
    assert contacto["parentesco"] == "madre"

    # Y ya puede entrar por el camino normal
    entrada = await cliente.post("/auth/solicitar-token", json={"cedula": CED_SIN_CORREO})
    assert entrada.status_code == 200


async def test_el_permiso_se_usa_una_sola_vez(cliente, sin_correo):
    prueba = await cliente.post("/auth/probar-identidad", json={
        "cedula": CED_SIN_CORREO,
        "fecha_nacimiento": NACIMIENTO, "fecha_ingreso": INGRESO,
    })
    cuerpo = {
        "token": prueba.json()["token"], "email": "unavez@itsanet.com.ec",
        "telefono": "0991112223", "emergencia_nombre": "Contacto Prueba",
        "emergencia_parentesco": "otro", "emergencia_telefono": "0994445556",
    }
    assert (await cliente.post("/auth/completar-ficha", json=cuerpo)).status_code == 200
    segunda = await cliente.post("/auth/completar-ficha", json={**cuerpo, "email": "otro@itsanet.com.ec"})
    assert segunda.status_code == 410


async def test_no_se_puede_tomar_el_correo_de_otra_persona(cliente, sin_correo, empleado):
    """Registrar el correo de un compañero sería recibir sus códigos."""
    ajeno = "ocupado@itsanet.com.ec"
    # Un tercero, para no alterar al empleado que comparten las demás pruebas.
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values ('1700000027', 'Correo Ocupado', %s, 'empleado', current_date - 900)
           on conflict (cedula) do update set email = excluded.email returning id""",
        (ajeno,),
    )

    prueba = await cliente.post("/auth/probar-identidad", json={
        "cedula": CED_SIN_CORREO,
        "fecha_nacimiento": NACIMIENTO, "fecha_ingreso": INGRESO,
    })
    r = await cliente.post("/auth/completar-ficha", json={
        "token": prueba.json()["token"],
        "email": ajeno,                      # el de alguien más
        "telefono": "0991112223",
        "emergencia_nombre": "Contacto Prueba",
        "emergencia_parentesco": "otro",
        "emergencia_telefono": "0994445556",
    })
    assert r.status_code == 409
