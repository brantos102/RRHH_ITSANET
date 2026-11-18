"""Primer ingreso: confirmar el correo, el cargo y el jefe.

La planilla se cargó de una hoja de cálculo y nadie la contrastó nunca con
quien la vive: 225 personas quedaron con un correo inventado del estilo
«0927127886@pendiente.itsanet.local» —al que nunca llegará un código—, diez
sin jefe asignado y varios cargos desactualizados.

El primer ingreso es el único momento en que se tiene la atención de las 351
personas, así que es ahí donde se pregunta. Las reglas que fijan estas
pruebas:

  · El correo y los teléfonos los cambia la persona, sin que nadie apruebe
    nada. Del correo se comprueba que exista y sea suyo, y eso lo comprueba
    la dirección misma: hasta que se abre el enlace, sigue rigiendo el
    anterior.
  · El cargo y el jefe los puede señalar, pero no decidir. De quién depende
    cada quien define a dónde va su solicitud a autorizarse; lo confirma
    Talento Humano.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CED_JEFE = "1700000779"
CED_RRHH_C = "1700000035"
CED_SIN_CORREO_C = "1700000027"
NACIMIENTO = "1988-04-10"
INGRESO = "2021-02-01"


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
           values (%s, 'Talento Confirma', 'confirmarrhh@api.test', 'rrhh',
                   current_date - 900, 'Quito')
           on conflict (cedula) do update set rol = 'rrhh' returning id""",
        (CED_RRHH_C,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_C})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_C, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_RRHH_C,))


@pytest.fixture
async def jefe(empleado):
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, cargo,
                                     departamento, fecha_ingreso)
           values (%s, 'Jefa De Area', 'jefa@api.test', 'jefe',
                   'Jefa de Operaciones', 'OPERACIONES', current_date - 2000)
           on conflict (cedula) do update set rol = 'jefe' returning id""",
        (CED_JEFE,),
    )
    yield {"id": str(fila["id"]), "cedula": CED_JEFE}
    await ejecutar("delete from public.users where cedula = %s", (CED_JEFE,))


# ------------------------------------------------------- el correo se confirma
async def test_el_correo_no_rige_hasta_que_se_abre_el_enlace(cliente, auth, empleado):
    r = await cliente.post("/mi-ficha/correo", headers=auth,
                           json={"email": "bryan.nuevo@itsanet.com.ec"})
    assert r.status_code == 202, r.text
    assert "24 horas" in r.json()["mensaje"]

    fila = await obtener_uno(
        "select email::text as email from public.users where id = %s", (empleado["id"],))
    assert fila["email"] != "bryan.nuevo@itsanet.com.ec"

    # Y la ficha lo dice, para que la pantalla pueda avisarlo.
    ficha = await cliente.get("/mi-ficha", headers=auth)
    assert ficha.json()["persona"]["correo_por_confirmar"] == "bryan.nuevo@itsanet.com.ec"


async def test_un_enlace_vencido_no_aplica_nada(cliente, auth, empleado):
    await cliente.post("/mi-ficha/correo", headers=auth,
                       json={"email": "tarde@itsanet.com.ec"})
    await ejecutar(
        """update public.confirmaciones_correo set expira_en = now() - interval '1 minute'
            where user_id = %s""",
        (empleado["id"],))
    token = await obtener_uno(
        """select token::text as token from public.confirmaciones_correo
            where user_id = %s order by created_at desc limit 1""",
        (empleado["id"],))

    r = await cliente.post("/auth/confirmar-correo", json={"token": token["token"]})
    assert r.status_code == 410
    assert "venció" in r.json()["detail"]["mensaje"]

    fila = await obtener_uno(
        "select email::text as email from public.users where id = %s", (empleado["id"],))
    assert fila["email"] != "tarde@itsanet.com.ec"


async def test_pedirlo_de_nuevo_invalida_el_enlace_anterior(cliente, auth, empleado):
    """Un enlace viejo en la bandeja no debe aplicar una dirección descartada."""
    await cliente.post("/mi-ficha/correo", headers=auth,
                       json={"email": "primera@itsanet.com.ec"})
    primero = await obtener_uno(
        """select token::text as token from public.confirmaciones_correo
            where user_id = %s order by created_at desc limit 1""",
        (empleado["id"],))

    await cliente.post("/mi-ficha/correo", headers=auth,
                       json={"email": "segunda@itsanet.com.ec"})

    r = await cliente.post("/auth/confirmar-correo", json={"token": primero["token"]})
    assert r.status_code == 410


# --------------------------------------------------- el cargo y el jefe se señalan
async def test_confirmar_deja_constancia(cliente, auth, empleado):
    """Que alguien diga «está bien» es un dato, no un no-evento."""
    r = await cliente.post("/mi-ficha/confirmar", headers=auth,
                           json={"cargo_correcto": True, "jefe_correcto": True})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        """select cargo_confirmado_en, jefe_confirmado_en
             from public.users where id = %s""", (empleado["id"],))
    assert fila["cargo_confirmado_en"] is not None
    assert fila["jefe_confirmado_en"] is not None


async def test_corregir_el_jefe_queda_a_la_espera(cliente, auth, empleado, jefe):
    antes = await obtener_uno(
        "select jefe_id from public.users where id = %s", (empleado["id"],))

    r = await cliente.post("/mi-ficha/confirmar", headers=auth,
                           json={"cargo_correcto": True, "jefe_correcto": False,
                                 "jefe_propuesto_id": jefe["id"]})
    assert r.status_code == 200, r.text
    assert "Jefe que indica" in r.json()["en_revision"]

    despues = await obtener_uno(
        "select jefe_id from public.users where id = %s", (empleado["id"],))
    assert despues["jefe_id"] == antes["jefe_id"], "el jefe cambió sin confirmación"

    pendiente = await obtener_uno(
        """select estado, valor_nuevo from public.cambios_ficha
            where user_id = %s and campo = 'jefe_id'
            order by created_at desc limit 1""", (empleado["id"],))
    assert pendiente["estado"] == "pendiente"
    assert pendiente["valor_nuevo"] == jefe["id"]


async def test_al_aprobarlo_el_jefe_rige(cliente, auth, empleado, jefe, rrhh_auth):
    """La conversión de texto a uuid fallaba justo aquí, al aprobar."""
    await cliente.post("/mi-ficha/confirmar", headers=auth,
                       json={"cargo_correcto": True, "jefe_correcto": False,
                             "jefe_propuesto_id": jefe["id"]})
    cambio = await obtener_uno(
        """select id from public.cambios_ficha
            where user_id = %s and campo = 'jefe_id' and estado = 'pendiente'""",
        (empleado["id"],))

    r = await cliente.post(f"/rrhh/cambios-ficha/{cambio['id']}", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select jefe_id::text as jefe_id from public.users where id = %s", (empleado["id"],))
    assert fila["jefe_id"] == jefe["id"]


async def test_decir_que_esta_mal_sin_decir_cual_no_sirve(cliente, auth):
    r = await cliente.post("/mi-ficha/confirmar", headers=auth,
                           json={"cargo_correcto": False, "jefe_correcto": False})
    assert r.status_code == 422
    assert "cuál es su cargo" in r.json()["detail"]["mensaje"]


# ------------------------------------------------------------- la lista de jefes
async def test_la_lista_de_jefes_no_expone_datos_de_terceros(cliente, auth, jefe):
    r = await cliente.get("/catalogos/jefaturas", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json(), "la lista no debería venir vacía"
    for fila in r.json():
        assert set(fila) <= {"id", "nombre", "cargo", "departamento", "a_cargo"}, (
            f"la lista de jefes expone campos de más: {set(fila)}"
        )


async def test_nadie_se_ve_a_si_mismo_en_la_lista(cliente, auth, empleado, jefe):
    r = await cliente.get("/catalogos/jefaturas", headers=auth)
    assert empleado["id"] not in [f["id"] for f in r.json()]


# ---------------------------------------------------- el alta pregunta lo mismo
@pytest.fixture
async def sin_correo(empleado):
    fila = await obtener_uno(
        """insert into public.users
             (cedula, nombre, email, rol, cargo, fecha_ingreso, fecha_nacimiento,
              correo_pendiente, ficha_completa, ciudad)
           values (%s, 'Sin Correo Confirma', %s, 'empleado', 'Bodeguero', %s, %s,
                   true, false, 'Quito')
           on conflict (cedula) do update
             set correo_pendiente = true, ficha_completa = false,
                 cargo = 'Bodeguero',
                 fecha_nacimiento = excluded.fecha_nacimiento,
                 fecha_ingreso = excluded.fecha_ingreso
           returning id""",
        (CED_SIN_CORREO_C, f"{CED_SIN_CORREO_C}@pendiente.itsanet.local",
         INGRESO, NACIMIENTO),
    )
    yield {"id": str(fila["id"]), "cedula": CED_SIN_CORREO_C}
    await ejecutar("delete from public.users where cedula = %s", (CED_SIN_CORREO_C,))


async def test_la_prueba_de_identidad_muestra_que_hay_que_confirmar(cliente, sin_correo):
    r = await cliente.post("/auth/probar-identidad",
                           json={"cedula": CED_SIN_CORREO_C,
                                 "fecha_nacimiento": NACIMIENTO,
                                 "fecha_ingreso": INGRESO})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["cargo"] == "Bodeguero"
    assert "jefe" in cuerpo


async def test_el_alta_registra_la_correccion_del_cargo(cliente, sin_correo, jefe):
    identidad = await cliente.post("/auth/probar-identidad",
                                   json={"cedula": CED_SIN_CORREO_C,
                                         "fecha_nacimiento": NACIMIENTO,
                                         "fecha_ingreso": INGRESO})
    token = identidad.json()["token"]

    r = await cliente.post("/auth/completar-ficha", json={
        "token": token,
        "email": "confirma@itsanet.com.ec",
        "telefono": "0991234567",
        "emergencia_nombre": "Familiar Cercano",
        "emergencia_parentesco": "hermano",
        "emergencia_telefono": "0997654321",
        "cargo_correcto": False,
        "cargo_propuesto": "Asistente de Bodega",
        "jefe_correcto": False,
        "jefe_propuesto_id": jefe["id"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["en_revision"] == ["Cargo que indica", "Jefe que indica"]

    # El correo y el teléfono sí quedaron: no necesitan que nadie los apruebe.
    fila = await obtener_uno(
        """select email::text as email, telefono, cargo
             from public.users where id = %s""", (sin_correo["id"],))
    assert fila["email"] == "confirma@itsanet.com.ec"
    assert fila["telefono"] == "0991234567"
    # El cargo no: ese lo confirma Talento Humano.
    assert fila["cargo"] == "Bodeguero"

    pendientes = await obtener_todos(
        """select campo from public.cambios_ficha
            where user_id = %s and estado = 'pendiente'""", (sin_correo["id"],))
    assert {f["campo"] for f in pendientes} == {"cargo", "jefe_id"}


async def test_el_alta_deja_constancia_de_lo_confirmado(cliente, sin_correo):
    identidad = await cliente.post("/auth/probar-identidad",
                                   json={"cedula": CED_SIN_CORREO_C,
                                         "fecha_nacimiento": NACIMIENTO,
                                         "fecha_ingreso": INGRESO})
    r = await cliente.post("/auth/completar-ficha", json={
        "token": identidad.json()["token"],
        "email": "todobien@itsanet.com.ec",
        "telefono": "0991112223",
        "emergencia_nombre": "Familiar Cercano",
        "emergencia_telefono": "0997654321",
        "cargo_correcto": True,
        "jefe_correcto": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["en_revision"] == []

    fila = await obtener_uno(
        """select cargo_confirmado_en, jefe_confirmado_en
             from public.users where id = %s""", (sin_correo["id"],))
    assert fila["cargo_confirmado_en"] is not None
    assert fila["jefe_confirmado_en"] is not None


async def test_una_jefatura_inventada_no_tumba_el_alta(cliente, sin_correo):
    """Perder el correo recién escrito por un id inválido sería absurdo."""
    identidad = await cliente.post("/auth/probar-identidad",
                                   json={"cedula": CED_SIN_CORREO_C,
                                         "fecha_nacimiento": NACIMIENTO,
                                         "fecha_ingreso": INGRESO})
    r = await cliente.post("/auth/completar-ficha", json={
        "token": identidad.json()["token"],
        "email": "pese.al.error@itsanet.com.ec",
        "telefono": "0993334445",
        "emergencia_nombre": "Familiar Cercano",
        "emergencia_telefono": "0997654321",
        "cargo_correcto": True,
        "jefe_correcto": False,
        "jefe_propuesto_id": "00000000-0000-0000-0000-000000000000",
    })
    assert r.status_code == 200, r.text
    assert r.json()["avisos"], "debería avisar que la jefatura no existe"

    fila = await obtener_uno(
        "select email::text as email from public.users where id = %s", (sin_correo["id"],))
    assert fila["email"] == "pese.al.error@itsanet.com.ec"


async def test_la_bandeja_muestra_nombres_y_no_identificadores(
    cliente, auth, empleado, jefe, rrhh_auth
):
    """«144335b0-… → df160da3-…» no es algo que nadie pueda confirmar."""
    await cliente.post("/mi-ficha/confirmar", headers=auth,
                       json={"cargo_correcto": True, "jefe_correcto": False,
                             "jefe_propuesto_id": jefe["id"]})

    r = await cliente.get("/rrhh/cambios-ficha", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    fila = next(c for c in r.json()
                if c["campo"] == "jefe_id" and c["user_id"] == empleado["id"])
    assert fila["nuevo_legible"] == "Jefa De Area"
    assert fila["nuevo_legible"] != fila["valor_nuevo"]


async def test_reabrir_un_alta_no_choca_con_el_contacto_de_emergencia(
    cliente, sin_correo
):
    """Talento Humano puede reabrir un alta; el segundo intento debe pasar.

    Pasaba esto: el contacto de emergencia tiene un índice único por persona
    y el alta lo insertaba a ciegas. Al reabrirla —porque alguien tecleó mal
    su correo, que es exactamente cuando hace falta— el segundo intento moría
    con «El registro ya existe», después de haber guardado el correo y el
    teléfono nuevos. Ni la persona ni Talento Humano tenían cómo entenderlo.
    """
    async def completar(correo: str):
        identidad = await cliente.post("/auth/probar-identidad",
                                       json={"cedula": CED_SIN_CORREO_C,
                                             "fecha_nacimiento": NACIMIENTO,
                                             "fecha_ingreso": INGRESO})
        return await cliente.post("/auth/completar-ficha", json={
            "token": identidad.json()["token"],
            "email": correo,
            "telefono": "0991234567",
            "emergencia_nombre": "Familiar Cercano",
            "emergencia_telefono": "0997654321",
            "cargo_correcto": True, "jefe_correcto": True,
        })

    assert (await completar("primer.intento@itsanet.com.ec")).status_code == 200

    # Talento Humano reabre: la persona se equivocó de correo.
    await ejecutar(
        """update public.users set correo_pendiente = true, ficha_completa = false
            where cedula = %s""", (CED_SIN_CORREO_C,))

    r = await completar("corregido@itsanet.com.ec")
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select email::text as email from public.users where cedula = %s",
        (CED_SIN_CORREO_C,))
    assert fila["email"] == "corregido@itsanet.com.ec"

    contactos = await obtener_todos(
        """select nombre from public.emergency_contacts
            where user_id = %s and es_principal""", (sin_correo["id"],))
    assert len(contactos) == 1, "no debe duplicarse el contacto principal"
