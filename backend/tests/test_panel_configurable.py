"""Qué se ve en la pantalla principal, y quién puede cambiarlo.

El panel del colaborador se fue llenando de bloques y todos se mostraban
siempre a todo el mundo. Hacerlo configurable es fácil; hacerlo sin que un
administrador pueda dejar a 350 personas con una pantalla en blanco es lo que
estas pruebas cuidan.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)


@pytest.fixture
async def admin_auth(cliente, codigos):
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values ('1710034073', 'Admin Panel', 'admin.panel@api.test', 'admin',
                   current_date - 900)
           on conflict (cedula) do update set rol = 'admin', activo = true
           returning cedula""")
    await cliente.post("/auth/solicitar-token", json={"cedula": fila["cedula"]})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": fila["cedula"], "codigo": codigos[-1]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(autouse=True)
async def _panel_como_de_fabrica():
    """Cada prueba parte del panel recién instalado.

    Sin esto, una prueba que apaga un bloque deja apagadas las siguientes, y
    el fallo aparece en la prueba equivocada.
    """
    yield
    await ejecutar(
        """update public.panel_bloques
              set visible = true, roles = '{}', cuerpo = null,
                  actualizado_en = null, actualizado_por = null""")
    await ejecutar(
        """update public.panel_bloques b set orden = d.orden
             from (values ('anuncio',5),('alertas',10),('saldo',20),('antiguedad',30),
                          ('fines_semana',40),('acciones',50),('calendario',60),
                          ('firma',70),('logros',80),('solicitudes',90))
                  as d(clave, orden)
            where b.clave = d.clave""")


async def test_de_fabrica_el_panel_esta_entero(cliente, auth):
    """Instalar esto no cambia ni una pantalla. Es a propósito.

    Si después algo se ve distinto, la causa es un cambio que alguien hizo a
    conciencia, no la migración.
    """
    r = await cliente.get("/panel/bloques", headers=auth)
    assert r.status_code == 200, r.text
    claves = [b["clave"] for b in r.json()["bloques"]]
    assert "saldo" in claves and "solicitudes" in claves and "acciones" in claves
    # El aviso vacío no viaja: un recuadro sin texto no es un aviso.
    assert "anuncio" not in claves
    assert claves == sorted(claves, key=lambda c: claves.index(c))


async def test_lo_esencial_no_se_puede_apagar(cliente, admin_auth):
    """La prueba que justifica todo el módulo.

    Un administrador que apaga el saldo por error deja a 350 personas con una
    pantalla vacía y sin forma de pedir vacaciones.
    """
    for clave in ("saldo", "acciones", "solicitudes"):
        r = await cliente.patch(f"/panel/configuracion/{clave}",
                              headers=admin_auth, json={"visible": False})
        assert r.status_code == 422, f"{clave} se dejó apagar: {r.text}"
        assert "no se puede ocultar" in r.json()["detail"]["mensaje"].lower()

    visibles = await obtener_todos(
        "select clave from public.panel_bloques where esencial and not visible")
    assert not visibles


async def test_apagar_un_bloque_lo_quita_de_la_pantalla(cliente, auth, admin_auth):
    antes = [b["clave"] for b in (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]]
    assert "firma" in antes

    r = await cliente.patch("/panel/configuracion/firma",
                          headers=admin_auth, json={"visible": False})
    assert r.status_code == 200, r.text

    despues = [b["clave"] for b in (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]]
    assert "firma" not in despues
    assert "saldo" in despues


async def test_apagar_no_borra_nada(cliente, auth, admin_auth):
    """Es una decisión de presentación, no una baja de datos."""
    await cliente.patch("/panel/configuracion/calendario",
                      headers=admin_auth, json={"visible": False})
    # El calendario sigue sirviéndose por su propia ruta: el dato está.
    r = await cliente.get("/calendario", headers=auth)
    assert r.status_code == 200, r.text


async def test_reservar_un_bloque_a_jefatura(cliente, auth, jefe_auth, admin_auth):
    r = await cliente.patch("/panel/configuracion/calendario", headers=admin_auth,
                          json={"roles": ["jefe", "rrhh", "admin"]})
    assert r.status_code == 200, r.text

    del_empleado = [b["clave"] for b in
                    (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]]
    del_jefe = [b["clave"] for b in
                (await cliente.get("/panel/bloques", headers=jefe_auth)).json()["bloques"]]
    assert "calendario" not in del_empleado
    assert "calendario" in del_jefe


async def test_lo_reservado_no_viaja_al_navegador_del_que_no_lo_ve(
    cliente, auth, admin_auth
):
    """Mandarlo todo con un «no mires esto» es esconderlo donde cualquiera lo ve."""
    await cliente.patch("/panel/configuracion/calendario", headers=admin_auth,
                      json={"roles": ["admin"]})
    cuerpo = (await cliente.get("/panel/bloques", headers=auth)).text
    assert "calendario" not in cuerpo


async def test_el_aviso_se_escribe_y_se_borra(cliente, auth, admin_auth):
    r = await cliente.patch("/panel/configuracion/anuncio", headers=admin_auth,
                          json={"cuerpo": "El viernes 3 la planta cierra a las 13:00."})
    assert r.status_code == 200, r.text

    bloques = (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]
    aviso = next(b for b in bloques if b["clave"] == "anuncio")
    assert "viernes 3" in aviso["cuerpo"]

    # Borrarlo de verdad: un aviso viejo colgado para siempre es peor que
    # ninguno, porque la gente deja de leer el recuadro.
    r = await cliente.patch("/panel/configuracion/anuncio",
                          headers=admin_auth, json={"cuerpo": "   "})
    assert r.status_code == 200, r.text
    claves = [b["clave"] for b in
              (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]]
    assert "anuncio" not in claves


async def test_reordenar_respeta_el_orden_pedido(cliente, auth, admin_auth):
    orden = ["solicitudes", "saldo", "acciones", "alertas", "anuncio",
             "antiguedad", "fines_semana", "calendario", "firma", "logros"]
    r = await cliente.post("/panel/configuracion/orden",
                           headers=admin_auth, json={"claves": orden})
    assert r.status_code == 200, r.text

    bloques = (await cliente.get("/panel/bloques", headers=auth)).json()["bloques"]
    vistos = [b["clave"] for b in bloques]
    assert vistos[0] == "solicitudes"
    assert vistos.index("saldo") < vistos.index("acciones")
    # Con huecos entre bloques, para poder intercalar uno nuevo sin renumerar.
    assert bloques[0]["orden"] == 10


async def test_solo_el_administrador_configura(cliente, auth, rrhh_auth, jefe_auth):
    """Talento Humano administra personas; la cara del sistema, no."""
    for cabeceras in (auth, rrhh_auth, jefe_auth):
        r = await cliente.patch("/panel/configuracion/firma",
                              headers=cabeceras, json={"visible": False})
        assert r.status_code == 403, r.text
        r = await cliente.get("/panel/configuracion", headers=cabeceras)
        assert r.status_code == 403, r.text


async def test_sin_sesion_no_hay_panel(cliente):
    assert (await cliente.get("/panel/bloques")).status_code == 401


async def test_un_bloque_que_no_existe_se_dice_con_su_nombre(cliente, admin_auth):
    r = await cliente.patch("/panel/configuracion/inventado",
                          headers=admin_auth, json={"visible": False})
    assert r.status_code == 422
    assert "inventado" in r.json()["detail"]["mensaje"]


async def test_el_cambio_queda_firmado(cliente, admin_auth):
    await cliente.patch("/panel/configuracion/logros",
                      headers=admin_auth, json={"visible": False})
    fila = await obtener_uno(
        """select b.actualizado_en, u.rol
             from public.panel_bloques b
             join public.users u on u.id = b.actualizado_por
            where b.clave = 'logros'""")
    assert fila is not None and fila["rol"] == "admin"
    rastro = await obtener_uno(
        """select detalle from public.audit_logs
            where accion = 'panel.configurar' and entidad_id = 'logros'
            order by created_at desc limit 1""")
    assert rastro is not None
