"""Lo que hay que revisar a mano después de una carga inicial.

Esta pantalla nació de un hallazgo concreto: al probarla contra la planilla
real, las cuentas de prueba que se crearon al arrancar el sistema no estaban
sueltas. Estaban pegadas a personas de verdad, que hoy cargan con un correo
que no existe —así que no pueden recibir su código de acceso— y con roles de
mando que nadie les dio. Una de ellas figuraba como jefe de setenta y cuatro
personas.
"""
from __future__ import annotations

from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)


async def test_la_depuracion_reune_los_cinco_grupos(cliente, rrhh_auth):
    r = await cliente.get("/admin/depuracion", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for clave in ("cuentas_de_prueba", "fichas_incompletas", "jerarquia",
                  "sin_entrada", "historicas_imposibles", "resumen"):
        assert clave in cuerpo, clave


async def test_una_cuenta_de_prueba_con_historial_se_marca_como_persona_real(
    cliente, rrhh_auth, empleado
):
    """Es la distinción que importa: a una persona real se le corrige el
    correo; una cuenta de prueba de verdad se desactiva. Confundirlas
    significa desactivar a alguien que trabaja aquí."""
    await ejecutar(
        """insert into public.vacaciones_historicas
             (user_id, fecha_inicio, fecha_fin, dias, origen)
           values (%s, current_date - 400, current_date - 396, 5, 'prueba')
           on conflict do nothing""", (empleado["id"],))
    try:
        r = await cliente.get("/admin/depuracion", headers=rrhh_auth)
        cuentas = r.json()["cuentas_de_prueba"]
        mia = next((c for c in cuentas if c["cedula"] == empleado["cedula"]), None)
        assert mia is not None, "no detectó el correo de dominio de prueba"
        assert "persona real" in mia["que_hacer"].lower()
    finally:
        await ejecutar(
            "delete from public.vacaciones_historicas where user_id = %s and origen = 'prueba'",
            (empleado["id"],))


async def test_se_cuenta_la_gente_a_cargo_de_cada_cuenta_de_prueba(cliente, rrhh_auth):
    """Sin ese número no se puede decidir nada: desactivar a quien tiene
    setenta y cuatro personas asignadas las deja a todas sin jefe."""
    r = await cliente.get("/admin/depuracion", headers=rrhh_auth)
    for c in r.json()["cuentas_de_prueba"]:
        assert isinstance(c["a_cargo"], int)
        if c["a_cargo"] > 0:
            assert "reasígnela" in c["que_hacer"] or "real" in c["que_hacer"].lower()


async def test_un_empleado_sin_jefe_sale_en_jerarquia(cliente, rrhh_auth, empleado):
    anterior = await obtener_uno(
        "select jefe_id from public.users where id = %s", (empleado["id"],))
    await ejecutar("update public.users set jefe_id = null where id = %s", (empleado["id"],))
    try:
        r = await cliente.get("/admin/depuracion", headers=rrhh_auth)
        problemas = {j["cedula"]: j["problema"] for j in r.json()["jerarquia"]}
        assert empleado["cedula"] in problemas
        assert "Sin jefe" in problemas[empleado["cedula"]]
    finally:
        await ejecutar("update public.users set jefe_id = %s where id = %s",
                       (anterior["jefe_id"], empleado["id"]))


async def test_nadie_puede_llegar_a_ser_su_propio_jefe(cliente, empleado):
    """La base lo impide, así que la pantalla nunca tendrá que señalarlo.

    Se comprueba aquí porque la restricción es lo que hace innecesaria la
    revisión: si alguien la quitara, esta prueba lo diría antes de que una
    persona quedara autorizándose a sí misma sus propias vacaciones.
    """
    import pytest
    from psycopg import errors

    with pytest.raises(errors.CheckViolation):
        await ejecutar("update public.users set jefe_id = id where id = %s",
                       (empleado["id"],))


async def test_solo_talento_humano_ve_la_depuracion(cliente, auth, jefe_auth):
    """Lista quién no puede entrar y a quién le faltan datos: es información
    de Talento Humano, no de cualquiera con sesión."""
    for cabeceras in (auth, jefe_auth):
        assert (await cliente.get("/admin/depuracion",
                                  headers=cabeceras)).status_code == 403


async def test_sin_sesion_tampoco(cliente):
    assert (await cliente.get("/admin/depuracion")).status_code == 401
