"""Qué artículos de la ley lee el colaborador, y con qué palabras.

El panel imprimía el texto literal de cuatro artículos del Código del
Trabajo. Dos de ellos son los que terminan en discusión en el mostrador de
Talento Humano: el Art. 75 leído a secas parece una invitación a acumular, y
el Art. 76 un derecho a cobrar en lugar de descansar.

Estas pruebas cuidan tres cosas, y la tercera es la importante:

  · Que los tres modos —completo, resumen, oculto— funcionen de verdad y en
    todas las pantallas, no solo en la que se probó primero.
  · Que elegir «resumen» sin haberlo escrito no deje el artículo en blanco.
  · Que ocultar la CITA no oculte la CONSECUENCIA. «Tres días vencen el 30
    de junio» es lo que la persona necesita para actuar, y se dice aunque el
    artículo esté oculto. Si alguna vez se pierde eso, el interruptor habrá
    dejado de ser una decisión de redacción para convertirse en una forma de
    que nadie se enterara.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.test_panel_configurable import admin_auth  # noqa: F401
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)

PANEL = ("CT_ART_69", "CT_ART_73", "CT_ART_74", "CT_ART_75")


@pytest.fixture(autouse=True)
async def _leyes_como_de_fabrica():
    """Todos los artículos vuelven a su modo original al terminar.

    Una prueba que oculta el Art. 75 y se lo deja oculto haría fallar a la
    siguiente, y el fallo aparecería en la prueba equivocada.
    """
    antes = {f["codigo"]: (f["visibilidad"], f["resumen"]) for f in await obtener_todos(
        "select codigo, visibilidad, resumen from legal_references")}
    yield
    for codigo, (visibilidad, resumen) in antes.items():
        await ejecutar(
            """update legal_references
                  set visibilidad = %s, resumen = %s,
                      visibilidad_en = null, visibilidad_por = null
                where codigo = %s""",
            (visibilidad, resumen, codigo))


async def _modo(codigo: str, visibilidad: str) -> None:
    await ejecutar("update legal_references set visibilidad = %s where codigo = %s",
                   (visibilidad, codigo))


# ------------------------------------------------- nada cambia por omisión
async def test_de_fabrica_se_ve_el_texto_completo_de_los_cuatro(cliente, auth):
    """La instalación no esconde nada: la decisión es de Talento Humano."""
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    articulos = {a["codigo"]: a for a in d["base_legal"]}
    assert set(articulos) == set(PANEL)
    assert all(a["modo"] == "completo" for a in articulos.values())
    assert d["citar"] == {"art_69": True, "art_75": True}


async def test_todos_los_articulos_arrancan_en_completo():
    fila = await obtener_uno(
        "select count(*) as n from legal_references where visibilidad <> 'completo'")
    assert fila["n"] == 0


# --------------------------------------------------------------- oculto
async def test_oculto_desaparece_del_panel(cliente, auth):
    await _modo("CT_ART_75", "oculto")
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert "CT_ART_75" not in {a["codigo"] for a in d["base_legal"]}
    assert len(d["base_legal"]) == 3


async def test_oculto_quita_la_cita_de_la_explicacion_de_cada_periodo(cliente, auth):
    """La explicación del período llevaba «(Art. 69 CT)» escrito dentro."""
    antes = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert any("(Art. 69 CT)" in p["explicacion"] for p in antes["periodos"])

    await _modo("CT_ART_69", "oculto")
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert not any("Art. 69" in p["explicacion"] for p in d["periodos"])
    # Pero el período sigue explicándose: cambia la cita, no el contenido.
    assert all(p["explicacion"].strip() for p in d["periodos"])
    assert any("días base" in p["explicacion"] for p in d["periodos"])


async def test_oculto_avisa_a_la_pantalla_que_no_puede_citar(cliente, auth):
    """Lo que la pantalla necesita para no llevar «(Art. 75)» escrito."""
    await _modo("CT_ART_75", "oculto")
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert d["citar"]["art_75"] is False
    assert d["citar"]["art_69"] is True


async def test_el_saldo_no_cambia_porque_se_oculte_un_articulo(cliente, auth):
    """Ocultar una cita es un cambio de redacción. Si moviera un número sería un error."""
    antes = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    for codigo in PANEL:
        await _modo(codigo, "oculto")
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert d["base_legal"] == []
    for clave in ("saldo_total", "dias_por_anio_actual", "dias_ganados",
                  "dias_en_curso", "dias_caducados", "proximo_dias"):
        assert d[clave] == antes[clave], clave


# -------------------------------------------------------------- resumen
async def test_resumen_reemplaza_el_texto_y_lo_dice(cliente, auth):
    await _modo("CT_ART_75", "resumen")
    d = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    art = {a["codigo"]: a for a in d["base_legal"]}["CT_ART_75"]
    assert art["modo"] == "resumen"
    assert "no las pierde" in art["texto"]
    # El artículo se sigue citando: cambia la explicación, no el derecho.
    assert art["articulo"] == "Art. 75"
    assert d["citar"]["art_75"] is True


async def test_el_resumen_del_75_y_del_76_vienen_escritos():
    """Para no tener que redactarlos en la reunión con Talento Humano."""
    filas = await obtener_todos(
        "select codigo, resumen from legal_references where codigo = any(%s)",
        (["CT_ART_69", "CT_ART_73", "CT_ART_74", "CT_ART_75", "CT_ART_76"],))
    for f in filas:
        assert (f["resumen"] or "").strip(), f["codigo"]


async def test_el_resumen_del_76_dice_el_derecho_y_su_limite():
    """Citar el 76 suelto es lo que arma la discusión: se paga, pero al liquidar."""
    f = await obtener_uno(
        "select resumen from legal_references where codigo = 'CT_ART_76'")
    assert "se pagan" in f["resumen"]
    assert "liquidar" in f["resumen"]


async def test_resumen_sin_escribir_lo_rechaza_la_base():
    """Elegir resumen y dejarlo en blanco dejaría el artículo vacío."""
    with pytest.raises(Exception) as err:
        await ejecutar(
            """update legal_references
                  set visibilidad = 'resumen', resumen = null where codigo = 'CT_ART_73'""")
    assert "legal_resumen_si_resume" in str(err.value)


# ---------------------------------------------- el interruptor en las demás
async def test_el_catalogo_de_permisos_tambien_respeta_el_modo(cliente, auth):
    """Si el interruptor solo funcionara en el panel de saldo sería un adorno."""
    antes = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    por_codigo = {t["codigo"]: t for t in antes}
    assert por_codigo["calamidad_domestica"]["articulo"] == "Art. 42 núm. 30"

    await _modo("CT_ART_42_30", "oculto")
    d = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    calamidad = {t["codigo"]: t for t in d}["calamidad_domestica"]
    assert calamidad["articulo"] is None
    # Pero el tipo de permiso sigue ahí y se puede pedir.
    assert calamidad["nombre"]


async def test_el_glosario_no_devuelve_los_ocultos(cliente):
    await _modo("CT_ART_76", "oculto")
    codigos = {a["codigo"] for a in (await cliente.get("/glosario")).json()}
    assert "CT_ART_76" not in codigos
    assert "CT_ART_69" in codigos


async def test_el_glosario_devuelve_el_resumen_cuando_toca(cliente):
    await _modo("CT_ART_75", "resumen")
    art = {a["codigo"]: a
           for a in (await cliente.get("/glosario")).json()}["CT_ART_75"]
    assert art["modo"] == "resumen"
    assert "no las pierde" in art["texto"]


# --------------------------------------------------- quién puede cambiarlo
async def test_rrhh_ve_la_configuracion_de_la_base_legal(cliente, rrhh_auth):
    r = await cliente.get("/admin/base-legal", headers=rrhh_auth)
    assert r.status_code == 200
    articulos = {a["codigo"]: a for a in r.json()}
    assert articulos["CT_ART_75"]["sale_en_el_panel"] is True
    assert articulos["CT_ART_76"]["sale_en_el_panel"] is False
    # Quien configura ve el texto completo aunque esté oculto para los demás.
    assert articulos["CT_ART_75"]["texto"]
    assert articulos["CT_ART_75"]["resumen"]


async def test_rrhh_no_puede_cambiarlo_solo_administracion(cliente, rrhh_auth):
    """Decide lo que trescientas cincuenta personas leen."""
    r = await cliente.patch("/admin/base-legal/CT_ART_75", headers=rrhh_auth,
                            json={"visibilidad": "oculto"})
    assert r.status_code == 403
    f = await obtener_uno(
        "select visibilidad from legal_references where codigo = 'CT_ART_75'")
    assert f["visibilidad"] == "completo"


async def test_el_colaborador_no_llega_a_la_configuracion(cliente, auth):
    assert (await cliente.get("/admin/base-legal", headers=auth)).status_code == 403


async def test_administracion_cambia_el_modo_y_queda_en_la_bitacora(cliente, admin_auth):
    r = await cliente.patch("/admin/base-legal/CT_ART_75", headers=admin_auth,
                            json={"visibilidad": "resumen"})
    assert r.status_code == 200
    assert "Art. 75" in r.json()["mensaje"]
    assert "resumen" in r.json()["mensaje"]

    f = await obtener_uno(
        """select l.visibilidad, l.visibilidad_en, q.nombre
             from legal_references l
             left join users q on q.id = l.visibilidad_por
            where l.codigo = 'CT_ART_75'""")
    assert f["visibilidad"] == "resumen"
    assert f["visibilidad_en"] is not None
    assert f["nombre"] == "Admin Panel"

    reg = await obtener_uno(
        """select detalle from audit_logs
            where accion = 'base_legal_modificada' and entidad_id = 'CT_ART_75'
            order by created_at desc limit 1""")
    assert reg["detalle"]["antes"]["visibilidad"] == "completo"
    assert reg["detalle"]["ahora"]["visibilidad"] == "resumen"


async def test_se_puede_escribir_el_resumen_sin_activarlo(cliente, admin_auth):
    """Talento Humano redacta con calma y recién después decide mostrarlo."""
    r = await cliente.patch("/admin/base-legal/CT_ART_73", headers=admin_auth,
                            json={"resumen": "Las fechas se acuerdan con su jefe."})
    assert r.status_code == 200
    f = await obtener_uno(
        "select visibilidad, resumen from legal_references where codigo = 'CT_ART_73'")
    assert f["visibilidad"] == "completo"
    assert f["resumen"] == "Las fechas se acuerdan con su jefe."


async def test_resumen_en_blanco_se_explica_en_castellano(cliente, admin_auth):
    await ejecutar(
        "update legal_references set resumen = null where codigo = 'CT_ART_73'")
    r = await cliente.patch("/admin/base-legal/CT_ART_73", headers=admin_auth,
                            json={"visibilidad": "resumen"})
    assert r.status_code == 422
    assert "resumen" in r.json()["detail"]["mensaje"]


async def test_un_articulo_que_no_existe_no_revienta(cliente, admin_auth):
    r = await cliente.patch("/admin/base-legal/CT_ART_999", headers=admin_auth,
                            json={"visibilidad": "oculto"})
    assert r.status_code == 404


async def test_un_modo_inventado_se_rechaza(cliente, admin_auth):
    r = await cliente.patch("/admin/base-legal/CT_ART_75", headers=admin_auth,
                            json={"visibilidad": "borrado"})
    assert r.status_code == 422
