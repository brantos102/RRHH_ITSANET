"""Corregir un correo y toparse con «El registro ya existe».

Pasó en producción. Talento Humano abre la ficha de un colaborador para
corregirle el correo —el que tiene cargado está mal y por eso no le llega el
código de acceso—, escribe el bueno, guarda, y el sistema responde:

    El registro ya existe.

Y ahí se acaba. No dice qué campo chocó, de los diez del formulario, ni con
quién: la ficha que ya tiene ese correo NO está en la pantalla, puede ser de
otra área o estar inactiva. Quien lo lee se queda probando a ciegas, o
peor, concluye que el sistema está roto.

La causa es correcta y la restricción debe quedarse: un correo en dos fichas
significa que el código de acceso de una persona llega al buzón de otra. Lo
que estaba mal era el mensaje.

`users.email` es `citext`, así que el choque ocurre ignorando mayúsculas:
`JGanchoso@...` y `jganchoso@...` son el mismo correo. La búsqueda del
culpable tiene que hacerlo igual o diría que no encuentra a nadie.
"""
from __future__ import annotations

import pytest

from tests.conftest import Sql, persona
from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import CEDULA_RRHH_R, rrhh_auth  # noqa: F401

# Cédulas válidas (dígito verificador correcto) que no usa ninguna otra prueba.
CEDULA_A = "0914723788"
CEDULA_B = "1710034073"
CORREO = "duplicado.prueba@ejemplo-itsanet.com"
CEDULA_LIBRE = "1750000000"


@pytest.fixture
async def dos_fichas():
    """Una ficha con el correo puesto y otra sin correo."""
    con_correo = await persona(CEDULA_A, al_existir={"email": CORREO, "activo": True}, nombre='Quien Tiene El Correo', email=CORREO, rol='empleado', fecha_ingreso=Sql("current_date() - interval 400 day"), departamento='REDES')
    sin_correo = await persona(CEDULA_B, al_existir={"email": None, "activo": True}, nombre='Quien Lo Necesita', email=None, rol='empleado', fecha_ingreso=Sql("current_date() - interval 400 day"))
    yield {"con_correo": con_correo["id"], "sin_correo": sin_correo["id"]}
    await ejecutar("delete from users where cedula = any(%s)", ([CEDULA_A, CEDULA_B],))


async def test_el_mensaje_dice_de_quien_es_el_correo(cliente, rrhh_auth, dos_fichas):
    """Lo que faltaba: con quién choca."""
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                            headers=rrhh_auth, json={"email": CORREO})
    assert r.status_code == 409
    mensaje = r.json()["detail"]["mensaje"]
    assert "Quien Tiene El Correo" in mensaje, mensaje
    assert CEDULA_A in mensaje, mensaje
    assert "El registro ya existe" not in mensaje


async def test_tambien_dice_el_area_para_saber_a_quien_preguntar(cliente, rrhh_auth, dos_fichas):
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                            headers=rrhh_auth, json={"email": CORREO})
    assert r.status_code == 409, r.text
    assert "REDES" in r.json()["detail"]["mensaje"]


async def test_el_choque_sale_tambien_en_datos_para_la_pantalla(cliente, rrhh_auth, dos_fichas):
    """Para que la interfaz pueda ofrecer «ir a esa ficha» sin leer el texto."""
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                            headers=rrhh_auth, json={"email": CORREO})
    detalle = r.json()["detail"]
    assert detalle["restriccion"] == "users_email_key"
    assert detalle["lo_tiene"]["cedula"] == CEDULA_A
    assert detalle["lo_tiene"]["activo"] is True


async def test_choca_igual_aunque_cambien_las_mayusculas(cliente, rrhh_auth, dos_fichas):
    """`citext`: son el mismo correo, y el mensaje tiene que encontrarlo igual."""
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                            headers=rrhh_auth, json={"email": CORREO.upper()})
    assert r.status_code == 409
    assert "Quien Tiene El Correo" in r.json()["detail"]["mensaje"]


async def test_avisa_cuando_la_ficha_que_lo_tiene_esta_inactiva(cliente, rrhh_auth, dos_fichas):
    """El caso que más desconcierta: la ficha culpable no sale en la lista."""
    await ejecutar("update users set activo = false where id = %s",
                   (dos_fichas["con_correo"],))
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                            headers=rrhh_auth, json={"email": CORREO})
    assert r.status_code == 409
    mensaje = r.json()["detail"]["mensaje"]
    assert "inactiva" in mensaje, mensaje
    assert r.json()["detail"]["lo_tiene"]["activo"] is False


async def test_el_alta_con_cedula_repetida_tambien_se_explica(cliente, rrhh_auth, dos_fichas):
    r = await cliente.post("/admin/usuarios", headers=rrhh_auth, json={
        "cedula": CEDULA_A, "nombre": "Otra Persona Distinta",
        "email": "otra.persona@ejemplo-itsanet.com", "fecha_ingreso": "2024-01-15"})
    assert r.status_code == 409
    mensaje = r.json()["detail"]["mensaje"]
    assert "Quien Tiene El Correo" in mensaje, mensaje
    assert CEDULA_A in mensaje


async def test_el_alta_con_correo_repetido_tambien(cliente, rrhh_auth, dos_fichas):
    # Una cédula libre: si chocara también por cédula, saltaría esa regla
    # primero y la prueba no comprobaría lo que dice comprobar.
    r = await cliente.post("/admin/usuarios", headers=rrhh_auth, json={
        "cedula": CEDULA_LIBRE, "nombre": "Otra Persona Mas",
        "email": CORREO, "fecha_ingreso": "2024-01-15"})
    assert r.status_code == 409, r.text
    assert "Quien Tiene El Correo" in r.json()["detail"]["mensaje"]
    await ejecutar("delete from users where cedula = %s", (CEDULA_LIBRE,))


async def test_la_restriccion_sigue_en_pie(cliente, rrhh_auth, dos_fichas):
    """Lo que NO debía cambiar: un correo en dos fichas manda el código de
    acceso de una persona al buzón de otra."""
    await cliente.patch(f"/admin/usuarios/{dos_fichas['sin_correo']}",
                        headers=rrhh_auth, json={"email": CORREO})
    cuantas = await obtener_uno(
        "select count(*) as n from users where email = %s", (CORREO,))
    assert cuantas["n"] == 1, "el correo quedó en dos fichas"


async def test_guardar_el_mismo_correo_de_siempre_no_falla(cliente, rrhh_auth, dos_fichas):
    """Reguardar una ficha sin tocar el correo no puede dar conflicto."""
    r = await cliente.patch(f"/admin/usuarios/{dos_fichas['con_correo']}",
                            headers=rrhh_auth, json={"email": CORREO, "cargo": "Analista"})
    assert r.status_code == 200, r.text
