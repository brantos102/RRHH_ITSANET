"""El alta de quien YA tiene su expediente completo.

El caso que lo motivó tiene nombre y apellido en la planilla real: una
persona con cargo, jefe, teléfono y contacto de emergencia ya registrados,
a la que el primer ingreso le volvía a pedir todo. Lo único que de verdad
falta es el correo —por eso no puede recibir su código—, y pedirle de nuevo
lo que el sistema ya sabe es la forma más rápida de que decida que el
sistema no sabe nada.

La comprobación de identidad SÍ se queda: sin correo no hay a dónde
escribirle, así que lo único que acredita que es quien dice ser son dos
datos que ya constan. Eso no es pedirle un dato: es compararlo.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.db import ejecutar, obtener_uno

CEDULA_COMPLETO = "0914723788"


@pytest.fixture
async def ficha_completa_sin_correo():
    """Alguien con TODO menos el correo: el caso de la planilla real."""
    fila = await obtener_uno(
        """insert into public.users
             (cedula, nombre, email, correo_pendiente, ficha_completa, rol,
              fecha_ingreso, fecha_nacimiento, telefono, direccion, cargo, departamento)
           values (%s, 'Prueba Expediente Completo', null, true, false, 'empleado',
                   date '2019-03-11', date '1990-07-22', '0987654321',
                   'Av. Siempre Viva 742', 'Estibador', 'ALMACENAMIENTO')
           on conflict (cedula) do update
             set correo_pendiente = true, ficha_completa = false, email = null,
                 telefono = '0987654321', direccion = 'Av. Siempre Viva 742'
           returning id""",
        (CEDULA_COMPLETO,),
    )
    await ejecutar(
        """insert into public.emergency_contacts
             (user_id, nombre, parentesco, telefono, es_principal)
           values (%s, 'Contacto Ya Registrado', 'madre', '0991112223', true)
           on conflict (user_id) where es_principal do update
             set nombre = excluded.nombre""",
        (fila["id"],),
    )
    yield {"id": str(fila["id"]), "cedula": CEDULA_COMPLETO}
    await ejecutar("delete from public.emergency_contacts where user_id = %s", (fila["id"],))
    await ejecutar("delete from public.altas_pendientes where user_id = %s", (fila["id"],))
    await ejecutar("delete from public.users where cedula = %s", (CEDULA_COMPLETO,))


async def _probar(cliente, cedula):
    return await cliente.post("/auth/probar-identidad", json={
        "cedula": cedula,
        "fecha_nacimiento": "1990-07-22",
        "fecha_ingreso": "2019-03-11",
    })


async def test_el_sistema_dice_que_es_lo_que_ya_tiene(cliente, ficha_completa_sin_correo):
    """Para que la pantalla pueda no volver a preguntarlo."""
    r = await _probar(cliente, ficha_completa_sin_correo["cedula"])
    assert r.status_code == 200, r.text
    ya = r.json()["ya_consta"]
    assert ya["telefono"] == "0987654321"
    assert ya["direccion"] == "Av. Siempre Viva 742"
    assert ya["emergencia"] == "Contacto Ya Registrado"


async def test_basta_con_el_correo_cuando_lo_demas_ya_consta(
    cliente, ficha_completa_sin_correo
):
    """Es el punto entero: solo falta el correo, solo se pide el correo."""
    token = (await _probar(cliente, ficha_completa_sin_correo["cedula"])).json()["token"]
    r = await cliente.post("/auth/completar-ficha", json={
        "token": token, "email": "expediente.completo@itsanet.com.ec",
    })
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        """select email, telefono, direccion, correo_pendiente, ficha_completa
             from public.users where cedula = %s""", (ficha_completa_sin_correo["cedula"],))
    assert fila["email"] == "expediente.completo@itsanet.com.ec"
    assert fila["correo_pendiente"] is False
    assert fila["ficha_completa"] is True
    # Y lo que ya tenía sigue ahí: no se borró por no haberlo repreguntado.
    assert fila["telefono"] == "0987654321"
    assert fila["direccion"] == "Av. Siempre Viva 742"


async def test_el_contacto_de_emergencia_no_se_pisa_con_nulos(
    cliente, ficha_completa_sin_correo
):
    """Borrarlo sería peor que no tenerlo: es a quien se avisa si algo pasa."""
    token = (await _probar(cliente, ficha_completa_sin_correo["cedula"])).json()["token"]
    await cliente.post("/auth/completar-ficha", json={
        "token": token, "email": "otro.expediente@itsanet.com.ec"})

    fila = await obtener_uno(
        """select nombre, telefono from public.emergency_contacts
            where user_id = %s and es_principal""", (ficha_completa_sin_correo["id"],))
    assert fila["nombre"] == "Contacto Ya Registrado"
    assert fila["telefono"] == "0991112223"


async def test_a_quien_NO_tiene_telefono_sigue_pidiendosele(cliente, ficha_completa_sin_correo):
    """Opcional en la petición no es opcional en el resultado."""
    await ejecutar("delete from public.emergency_contacts where user_id = %s",
                   (ficha_completa_sin_correo["id"],))
    await ejecutar("update public.users set telefono = null where id = %s",
                   (ficha_completa_sin_correo["id"],))

    token = (await _probar(cliente, ficha_completa_sin_correo["cedula"])).json()["token"]
    r = await cliente.post("/auth/completar-ficha", json={
        "token": token, "email": "sin.telefono@itsanet.com.ec"})
    assert r.status_code == 422
    mensaje = r.json()["detail"]["mensaje"]
    assert "teléfono" in mensaje and "contacto de emergencia" in mensaje


async def test_quien_declara_uno_nuevo_lo_reemplaza(cliente, ficha_completa_sin_correo):
    token = (await _probar(cliente, ficha_completa_sin_correo["cedula"])).json()["token"]
    r = await cliente.post("/auth/completar-ficha", json={
        "token": token, "email": "cambia.telefono@itsanet.com.ec",
        "telefono": "0955556667",
    })
    assert r.status_code == 200, r.text
    fila = await obtener_uno("select telefono from public.users where cedula = %s",
                             (ficha_completa_sin_correo["cedula"],))
    assert fila["telefono"] == "0955556667"


async def test_la_comprobacion_de_identidad_sigue_en_pie(cliente, ficha_completa_sin_correo):
    """Sin correo no hay a dónde escribirle: las dos fechas son la única
    puerta. Quitarlas dejaría registrar un correo contra cualquier cédula."""
    r = await cliente.post("/auth/probar-identidad", json={
        "cedula": ficha_completa_sin_correo["cedula"],
        "fecha_nacimiento": "1990-07-23",     # un día de diferencia
        "fecha_ingreso": "2019-03-11",
    })
    assert r.status_code == 404


async def test_no_se_expone_el_expediente_a_quien_solo_teclea_una_cedula(
    cliente, ficha_completa_sin_correo
):
    """La cédula en Ecuador es casi pública: lo que ya consta solo se
    devuelve DESPUÉS de probar la identidad."""
    r = await cliente.post("/auth/necesita-ficha",
                           json={"cedula": ficha_completa_sin_correo["cedula"]})
    assert r.status_code == 200
    assert set(r.json()) == {"necesita"}, "no debe filtrar nada más"
