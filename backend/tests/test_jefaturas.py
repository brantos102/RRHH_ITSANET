"""Agregar y quitar jefaturas sin dejar a nadie sin a quién pedir permiso.

La baja es lo delicado. Quitarle el rol de jefe a alguien con gente a cargo
no rompe nada visible: la pantalla guarda, el rol cambia y no sale ningún
error. Lo que queda roto es el circuito. Sus colaboradores siguen
apuntándole en `users.jefe_id`, piden vacaciones, y el pedido queda dirigido
a alguien que ya no tiene permiso para resolverlo.

En la planilla real hay una jefatura con setenta y cuatro personas a cargo.
Estas pruebas existen para que ese clic no vuelva a ser posible sin decir
antes a quién pasan.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)

CEDULA_OTRA_JEFATURA = "0900000019"


@pytest.fixture
async def otra_jefatura():
    """Una segunda jefatura, que es la que recibirá la gente."""
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, departamento)
           values (%s, 'API Jefatura Dos', 'jefatura3@api.test', 'jefe',
                   current_date - 2000, 'Bodega')
           on conflict (cedula) do update set rol = 'jefe' returning id""",
        (CEDULA_OTRA_JEFATURA,),
    )
    yield str(fila["id"])
    await ejecutar("update public.users set jefe_id = null where jefe_id = %s", (fila["id"],))
    await ejecutar("delete from public.users where cedula = %s", (CEDULA_OTRA_JEFATURA,))


# ---------------------------------------------------------------- la lista
async def test_la_lista_dice_cuanta_gente_tiene_cada_jefatura(cliente, rrhh_auth, jefe_auth):
    r = await cliente.get("/admin/jefaturas", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    jefaturas = r.json()
    mia = next((j for j in jefaturas if j["nombre"] == "API Jefatura"), None)
    assert mia is not None, "la jefatura de la prueba no figura en la lista"
    assert mia["a_cargo"] >= 1
    assert "esperando" in mia and "puede_entrar" in mia


async def test_la_lista_no_expone_cedula_ni_correo_de_terceros(cliente, rrhh_auth, jefe_auth):
    """Para decidir una jefatura no hace falta el dato personal (LOPDP, Art. 10)."""
    fila = (await cliente.get("/admin/jefaturas", headers=rrhh_auth)).json()[0]
    assert "cedula" not in fila
    assert "email" not in fila
    assert "telefono" not in fila


async def test_un_empleado_no_ve_la_lista_de_jefaturas(cliente, auth):
    r = await cliente.get("/admin/jefaturas", headers=auth)
    assert r.status_code == 403


# ------------------------------------------------------------------- alta
async def test_nombrar_jefatura_a_un_empleado(cliente, rrhh_auth, empleado):
    r = await cliente.post("/admin/jefaturas", headers=rrhh_auth,
                           json={"persona_id": empleado["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["cambio"] is True
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (empleado["id"],))
    assert fila["rol"] == "jefe"


async def test_nombrar_dos_veces_no_es_un_error_pero_lo_dice(cliente, rrhh_auth, empleado):
    await cliente.post("/admin/jefaturas", headers=rrhh_auth, json={"persona_id": empleado["id"]})
    r = await cliente.post("/admin/jefaturas", headers=rrhh_auth,
                           json={"persona_id": empleado["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["cambio"] is False
    assert "ya es jefatura" in r.json()["mensaje"]


async def test_a_talento_humano_no_se_le_baja_a_jefe(cliente, rrhh_auth):
    """Talento Humano aprueba por su rol: nombrarlo jefe le quitaría alcance."""
    rrhh = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_RRHH_R,))
    r = await cliente.post("/admin/jefaturas", headers=rrhh_auth,
                           json={"persona_id": str(rrhh["id"])})
    assert r.json()["cambio"] is False
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (rrhh["id"],))
    assert fila["rol"] == "rrhh"


# ------------------------------------------------------------------- baja
async def test_no_se_quita_una_jefatura_con_gente_sin_decir_a_quien_pasa(
    cliente, rrhh_auth, jefe_auth
):
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))
    r = await cliente.post(f"/admin/jefaturas/{jefe['id']}/quitar", headers=rrhh_auth,
                           json={"rol_destino": "empleado"})
    assert r.status_code >= 400
    assert "a cargo" in r.text
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (jefe["id"],))
    assert fila["rol"] == "jefe", "le quitó el mando pese a tener gente"


async def test_al_quitarla_la_gente_y_los_pendientes_pasan_a_la_otra_jefatura(
    cliente, rrhh_auth, jefe_auth, otra_jefatura, empleado
):
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))

    # Una solicitud esperando su firma: es lo que se queda huérfano en silencio.
    # Un permiso y no vacaciones, para no arrastrar aquí la regla de los
    # fines de semana obligatorios, que no tiene nada que ver con esto.
    tipo = await obtener_uno(
        """select id from public.permission_types
            where activo and not requiere_adjunto and not requiere_firma
            order by id limit 1""")
    await ejecutar(
        """insert into public.requests
             (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
              dias_solicitados, justificacion, descripcion, jefe_id, estado)
           values (%s, 'permiso', %s, current_date + 40, current_date + 40, 1,
                   'Traslado de jefatura en pruebas', 'Prueba de traslado de jefatura', %s, 'pendiente_jefe')""",
        (empleado["id"], tipo["id"], jefe["id"]),
    )

    r = await cliente.post(f"/admin/jefaturas/{jefe['id']}/quitar", headers=rrhh_auth,
                           json={"nuevo_jefe_id": otra_jefatura, "rol_destino": "empleado"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["personas_movidas"] >= 1
    assert cuerpo["solicitudes_movidas"] >= 1

    quedaron = await obtener_todos(
        "select id from public.users where jefe_id = %s and activo", (jefe["id"],))
    assert not quedaron, "quedó gente apuntando a quien ya no puede aprobarle nada"

    pendiente = await obtener_uno(
        """select jefe_id from public.requests
            where user_id = %s and estado = 'pendiente_jefe'""", (empleado["id"],))
    assert str(pendiente["jefe_id"]) == otra_jefatura


async def test_la_baja_es_una_sola_operacion_y_se_deshace_entera(
    cliente, rrhh_auth, jefe_auth
):
    """Si el destino no sirve, no se mueve nadie NI se le quita el mando."""
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))
    r = await cliente.post(f"/admin/jefaturas/{jefe['id']}/quitar", headers=rrhh_auth,
                           json={"nuevo_jefe_id": str(jefe["id"]), "rol_destino": "empleado"})
    assert r.status_code >= 400
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (jefe["id"],))
    assert fila["rol"] == "jefe"


async def test_quien_recibe_la_gente_no_termina_siendo_su_propio_jefe(
    cliente, rrhh_auth, jefe_auth, otra_jefatura
):
    """El caso que rompe la base: el receptor le reportaba al que se va."""
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (jefe["id"], otra_jefatura))

    r = await cliente.post(f"/admin/jefaturas/{jefe['id']}/quitar", headers=rrhh_auth,
                           json={"nuevo_jefe_id": otra_jefatura, "rol_destino": "empleado"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("select jefe_id from public.users where id = %s", (otra_jefatura,))
    assert str(fila["jefe_id"] or "") != otra_jefatura


async def test_nadie_se_quita_su_propia_jefatura(cliente, rrhh_auth):
    rrhh = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_RRHH_R,))
    r = await cliente.post(f"/admin/jefaturas/{rrhh['id']}/quitar", headers=rrhh_auth,
                           json={"rol_destino": "empleado"})
    assert r.status_code >= 400
    assert "propia jefatura" in r.text


# ---------------------------------------------- la puerta de atrás, cerrada
async def test_el_cambio_de_rol_suelto_ya_no_deja_gente_colgando(
    cliente, rrhh_auth, jefe_auth
):
    """Es la vía por la que esto pasaba: editar el rol desde Usuarios."""
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))
    r = await cliente.patch(f"/admin/usuarios/{jefe['id']}", headers=rrhh_auth,
                            json={"rol": "empleado"})
    assert r.status_code == 409, r.text
    assert "Jefaturas" in r.text
    fila = await obtener_uno("select rol::text as rol from public.users where id = %s",
                             (jefe["id"],))
    assert fila["rol"] == "jefe"


async def test_a_una_jefatura_sin_gente_se_le_cambia_el_rol_sin_trabas(
    cliente, rrhh_auth, otra_jefatura
):
    r = await cliente.patch(f"/admin/usuarios/{otra_jefatura}", headers=rrhh_auth,
                            json={"rol": "empleado"})
    assert r.status_code == 200, r.text


async def test_ascender_a_una_jefatura_sigue_siendo_un_cambio_de_rol(
    cliente, rrhh_auth, jefe_auth
):
    """El guardia es sobre quien nadie manda: subirlo no toca a nadie."""
    jefe = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_JEFE_R,))
    r = await cliente.patch(f"/admin/usuarios/{jefe['id']}", headers=rrhh_auth,
                            json={"rol": "rrhh"})
    assert r.status_code == 200, r.text
