"""Los dos papeles que el colaborador firma a mano y presenta en Talento Humano.

Son dos documentos con reglas de emisión opuestas, y confundirlas es el error
que estas pruebas vigilan:

  TRAZABILIDAD — el historial completo. UNA SOLA VEZ, al registrarse la
  primera solicitud de vacaciones. No se vuelve a emitir salvo autorización
  expresa con motivo. El ejemplar ya firmado NO cambia: una reemisión es un
  documento nuevo, con folio nuevo, y el anterior sigue siendo válido.

  SOLICITUD — solo lo pedido en esa sesión. SIEMPRE, con cada solicitud, y
  reimprimible cuantas veces haga falta.

Lo que más importa de todo: la trazabilidad guarda una FOTO de lo que decía.
Si Talento Humano corrige mañana un registro de 2019, el papel firmado ayer
no cambia. Reimprimirlo con los datos de hoy sería falsificar lo que se firmó.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_panel_configurable import admin_auth  # noqa: F401
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)


@pytest.fixture(autouse=True)
async def _sin_papeles_de_antes(empleado):
    """Cada prueba parte de una persona sin ningún papel emitido.

    La regla central es «una sola vez en la vida», así que un papel que
    sobrevive de la prueba anterior hace fallar a la siguiente por el motivo
    equivocado.
    """
    await ejecutar("delete from informes_firmados where user_id = %s",
                   (empleado["id"],))
    yield
    await ejecutar("delete from informes_firmados where user_id = %s",
                   (empleado["id"],))


async def _pedir_vacaciones(cliente, auth, dias: int = 7) -> dict:
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=dias)),
        "descripcion": "Descanso programado con la familia", "firmar": False})
    assert r.status_code == 201, r.text
    return r.json()


async def _papeles(empleado, tipo: str | None = None) -> list[dict]:
    extra = "and tipo = %s" if tipo else ""
    return await obtener_todos(
        f"""select id, tipo as tipo, folio, request_id, datos, impresiones,
                   autorizado_por, autorizacion_motivo
              from informes_firmados
             where user_id = %s {extra}
             order by emitido_en""",
        (empleado["id"], tipo) if tipo else (empleado["id"],))


# ------------------------------------------------------- se emiten solos
async def test_la_primera_solicitud_emite_los_dos_papeles(cliente, auth, empleado):
    assert await _papeles(empleado) == []
    await _pedir_vacaciones(cliente, auth)
    tipos = [p["tipo"] for p in await _papeles(empleado)]
    assert sorted(tipos) == ["solicitud", "trazabilidad"]


async def test_la_segunda_solicitud_no_vuelve_a_emitir_la_trazabilidad(
        cliente, auth, jefe_auth, rrhh_auth, empleado):
    """La regla central: el historial se firma una vez, no en cada solicitud."""
    primera = await _pedir_vacaciones(cliente, auth)
    trazas = await _papeles(empleado, "trazabilidad")
    assert len(trazas) == 1

    # Se resuelve la primera para poder pedir otra sin solaparse.
    for etapa in (jefe_auth, rrhh_auth):
        await cliente.post(f"/aprobaciones/{primera['id']}/decidir", headers=etapa,
                           json={"accion": "aprobar"})
    lunes = await lunes_sin_feriados(semanas=10)
    segunda = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Segundo bloque del periodo", "firmar": False,
        # El primer bloque ya consumió el saldo, así que el segundo es un
        # adelanto y el adelanto exige justificación. No es lo que esta
        # prueba mide; solo hay que dejarla pasar.
        "justificacion": "Talento Humano autorizó tomar el periodo en dos bloques."})
    assert segunda.status_code == 201, segunda.text

    assert len(await _papeles(empleado, "trazabilidad")) == 1, \
        "el historial no se vuelve a emitir con cada solicitud"
    assert len(await _papeles(empleado, "solicitud")) == 2, \
        "el formulario de la solicitud sí sale cada vez"


async def test_el_de_la_solicitud_apunta_a_su_solicitud(cliente, auth, empleado):
    pedida = await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "solicitud"))[0]
    assert str(papel["request_id"]) == pedida["id"]


async def test_un_permiso_no_emite_ningun_papel_de_vacaciones(cliente, auth, empleado):
    """El formulario es de vacaciones. Un permiso por horas no lo necesita."""
    tipos = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    tipo = [t for t in tipos if not t["requiere_adjunto"]][0]
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
        "descripcion": "Diligencia bancaria de la manana",
        "justificacion": "Tengo turno asignado en el banco."})
    assert r.status_code == 201, r.text
    assert await _papeles(empleado) == []


# ------------------------------------------------- la base sostiene la regla
async def test_la_base_impide_dos_trazabilidades_sin_autorizar(cliente, auth, empleado):
    """La regla no depende de que todas las rutas se acuerden de comprobarla."""
    await _pedir_vacaciones(cliente, auth)
    with pytest.raises(Exception) as err:
        await ejecutar(
            """insert into informes_firmados (user_id, tipo, folio, datos)
               values (%s, 'trazabilidad', 'TRZ-MANO-1', '{}')""",
            (empleado["id"],))
    assert "idx_trazabilidad_una_sola_vez" in str(err.value)


async def test_una_reemision_sin_motivo_no_entra(empleado):
    with pytest.raises(Exception) as err:
        await ejecutar(
            """insert into informes_firmados
                 (user_id, tipo, folio, autorizado_por, autorizado_en, datos)
               values (%s, 'trazabilidad', 'TRZ-MANO-2', %s, now(6), '{}')""",
            (empleado["id"], empleado["id"]))
    assert "informe_autorizacion_completa" in str(err.value)


async def test_el_de_trazabilidad_no_admite_solicitud_y_al_contrario(empleado):
    with pytest.raises(Exception) as err:
        await ejecutar(
            """insert into informes_firmados (user_id, tipo, folio, datos)
               values (%s, 'solicitud', 'SOL-MANO-1', '{}')""",
            (empleado["id"],))
    assert "informe_solicitud_con_solicitud" in str(err.value)


# ------------------------------------------------------------- la foto
async def test_la_trazabilidad_guarda_lo_que_decia_y_no_lo_que_dira(
        cliente, auth, empleado):
    """Reimprimir con los datos de hoy sería falsificar lo que se firmó."""
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    antes = papel["datos"]["totales"]["veces"]

    # Talento Humano carga un registro histórico que antes no estaba.
    await ejecutar(
        """insert into vacaciones_historicas
             (user_id, fecha_inicio, fecha_fin, dias, fila_origen)
           values (%s, date '2019-03-04', date '2019-03-15', 10, 9001)""",
        (empleado["id"],))
    try:
        de_nuevo = (await _papeles(empleado, "trazabilidad"))[0]
        assert de_nuevo["datos"]["totales"]["veces"] == antes, \
            "el papel firmado no cambia porque cambie la base"
        # Y lo que diría hoy un papel nuevo sí lo incluye.
        fila = await obtener_uno(
            "select datos_informe_trazabilidad(%s) as d", (empleado["id"],))
        assert fila["d"]["totales"]["veces"] == antes + 1
    finally:
        await ejecutar(
            "delete from vacaciones_historicas where fila_origen = 9001")


async def test_el_de_la_solicitud_si_se_actualiza_al_reimprimirlo(
        cliente, auth, jefe_auth, rrhh_auth, empleado):
    """Al contrario que el otro: un formulario que dijera «pendiente» cuando ya
    está aprobado no serviría de nada en el mostrador."""
    pedida = await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "solicitud"))[0]
    assert papel["datos"]["solicitud"]["aprobada"] is False

    for etapa in (jefe_auth, rrhh_auth):
        await cliente.post(f"/aprobaciones/{pedida['id']}/decidir", headers=etapa,
                           json={"accion": "aprobar"})
    await obtener_uno("select informe_solicitud_asegurar(%s)", (pedida["id"],))

    de_nuevo = (await _papeles(empleado, "solicitud"))[0]
    assert de_nuevo["folio"] == papel["folio"], "mismo documento, no uno nuevo"
    assert de_nuevo["datos"]["solicitud"]["aprobada"] is True


# ------------------------------------------------------- lo que se imprime
async def test_la_constancia_sale_imprimible_y_completa(cliente, auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    r = await cliente.get(f"/papeles/{papel['id']}.html", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    # Las cuatro cosas que tiene que llevar un papel que se firma.
    assert "Constancia de goce de vacaciones" in html
    assert papel["folio"] in html
    assert "Registro de vacaciones gozadas" in html.replace("REGISTRO", "Registro")
    for rol in ("Jefe inmediato", "Trabajador", "Responsable de Talento Humano"):
        assert rol in html, rol
    assert "Art. 326" in html, "la firma no renuncia a ningún derecho, y el papel lo dice"
    # Autosuficiente: en una bodega sin red, un papel a medias no sirve.
    assert "src=\"http" not in html and "href=\"http" not in html


async def test_el_formulario_de_la_solicitud_lleva_sus_cuatro_secciones(
        cliente, auth, empleado):
    pedida = await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "solicitud"))[0]
    html = (await cliente.get(f"/papeles/{papel['id']}.html", headers=auth)).text
    for seccion in ("Identificación del colaborador", "Programación y aprobación",
                    "Constancia de goce efectivo", "Declaración y firmas"):
        assert seccion in html, seccion
    assert "Nota de control interno" in html
    assert str(pedida["folio"]) in html
    # La casilla de Ordinarias marcada y la de Adelantadas vacía, o al revés.
    assert html.count('class="marca"') == 4


async def test_cada_impresion_queda_contada(cliente, auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    assert papel["impresiones"] == 0
    for _ in range(3):
        await cliente.get(f"/papeles/{papel['id']}.html", headers=auth)
    fila = await obtener_uno(
        "select impresiones, ultima_impresion from informes_firmados where id = %s",
        (papel["id"],))
    assert fila["impresiones"] == 3
    assert fila["ultima_impresion"] is not None


async def test_la_impresion_queda_en_la_bitacora(cliente, auth, empleado):
    """Quién vio el historial de quién: es un dato personal de 350 personas."""
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    await cliente.get(f"/papeles/{papel['id']}.html", headers=auth)
    reg = await obtener_uno(
        """select detalle from audit_logs
            where accion = 'papel_impreso' and entidad_id = %s
            order by created_at desc limit 1""", (str(papel["id"]),))
    assert reg is not None
    assert reg["detalle"]["tipo"] == "trazabilidad"
    assert reg["detalle"]["propio"] is True


# --------------------------------------------------------------- quién mira
async def test_el_jefe_inmediato_no_ve_el_historial_de_su_reporte(
        cliente, auth, jefe_auth, empleado):
    """Para autorizar cinco días no hace falta el historial completo de la persona."""
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    r = await cliente.get(f"/papeles/{papel['id']}.html", headers=jefe_auth)
    assert r.status_code == 403


async def test_talento_humano_si_lo_ve(cliente, auth, rrhh_auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    r = await cliente.get(f"/papeles/{papel['id']}.html", headers=rrhh_auth)
    assert r.status_code == 200


async def test_un_documento_inventado_da_404(cliente, auth):
    r = await cliente.get(
        "/papeles/00000000-0000-0000-0000-000000000000.html", headers=auth)
    assert r.status_code == 404


# ------------------------------------------------------------- reemisión
async def test_talento_humano_reemite_con_motivo(cliente, auth, rrhh_auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    primera = (await _papeles(empleado, "trazabilidad"))[0]

    r = await cliente.post(
        f"/admin/papeles/{empleado['id']}/reemitir-trazabilidad", headers=rrhh_auth,
        json={"motivo": "El colaborador perdió el ejemplar firmado en la bodega."})
    assert r.status_code == 200, r.text
    assert "sigue siendo válida" in r.json()["mensaje"]

    trazas = await _papeles(empleado, "trazabilidad")
    assert len(trazas) == 2
    assert trazas[0]["folio"] == primera["folio"], "la anterior no se toca"
    assert trazas[1]["folio"] != primera["folio"]
    assert trazas[1]["autorizado_por"] is not None
    assert "bodega" in trazas[1]["autorizacion_motivo"]


async def test_la_reemision_dice_en_el_papel_quien_la_autorizo(
        cliente, auth, rrhh_auth, empleado):
    """Para poder explicar en una auditoría por qué hay dos."""
    await _pedir_vacaciones(cliente, auth)
    r = await cliente.post(
        f"/admin/papeles/{empleado['id']}/reemitir-trazabilidad", headers=rrhh_auth,
        json={"motivo": "Se corrigió un registro de 2019 y hay que volver a firmar."})
    html = (await cliente.get(f"/papeles/{r.json()['id']}.html", headers=rrhh_auth)).text
    assert "Reemisión autorizada por" in html
    assert "API Talento" in html
    assert "registro de 2019" in html


async def test_una_reemision_sin_explicar_no_pasa(cliente, auth, rrhh_auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    r = await cliente.post(
        f"/admin/papeles/{empleado['id']}/reemitir-trazabilidad", headers=rrhh_auth,
        json={"motivo": "porque"})
    assert r.status_code == 422


async def test_el_colaborador_no_se_reemite_su_propio_historial(
        cliente, auth, empleado):
    """Es el punto de la regla: si pudiera, la constancia no constataría nada."""
    await _pedir_vacaciones(cliente, auth)
    r = await cliente.post(
        f"/admin/papeles/{empleado['id']}/reemitir-trazabilidad", headers=auth,
        json={"motivo": "Quiero uno nuevo porque el saldo ya cambió."})
    assert r.status_code == 403
    assert len(await _papeles(empleado, "trazabilidad")) == 1


async def test_no_se_reemite_lo_que_nunca_se_emitio(cliente, rrhh_auth, empleado):
    r = await cliente.post(
        f"/admin/papeles/{empleado['id']}/reemitir-trazabilidad", headers=rrhh_auth,
        json={"motivo": "Un motivo suficientemente largo para pasar la validación."})
    assert r.status_code == 422
    assert "no tiene todavía" in r.json()["detail"]["mensaje"]


# ----------------------------------------------------------- las pantallas
async def test_el_colaborador_ve_sus_papeles_y_la_regla_vigente(
        cliente, auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    r = await cliente.get("/papeles/mios", headers=auth)
    assert r.status_code == 200
    cuerpo = r.json()
    assert len(cuerpo["papeles"]) == 2
    # Para que la pantalla sepa si ofrecer el botón o decir a quién pedírselo.
    assert cuerpo["trazabilidad_reemision"] == "autorizada"


async def test_quien_ya_pedia_vacaciones_antes_puede_emitir_la_suya(
        cliente, auth, empleado):
    """Su primera solicitud no generó el papel porque el papel no existía."""
    assert await _papeles(empleado) == []
    r = await cliente.post("/papeles/trazabilidad", headers=auth)
    assert r.status_code == 200
    assert len(await _papeles(empleado, "trazabilidad")) == 1

    # Y pedirla dos veces no crea dos.
    segunda = await cliente.post("/papeles/trazabilidad", headers=auth)
    assert segunda.json()["folio"] == r.json()["folio"]
    assert len(await _papeles(empleado, "trazabilidad")) == 1


async def test_talento_humano_ve_quien_imprimio_que(cliente, auth, rrhh_auth, empleado):
    await _pedir_vacaciones(cliente, auth)
    papel = (await _papeles(empleado, "trazabilidad"))[0]
    await cliente.get(f"/papeles/{papel['id']}.html", headers=auth)

    r = await cliente.get("/admin/papeles", headers=rrhh_auth,
                          params={"tipo": "trazabilidad"})
    assert r.status_code == 200
    mio = {p["folio"]: p for p in r.json()}[papel["folio"]]
    assert mio["impresiones"] == 1
    assert mio["es_el_vigente"] is True
    assert mio["es_reemision"] is False
    # Sin esto el botón de reemitir de la pantalla sale sin a quién, y falla
    # recién al pulsarlo. Pasó.
    assert str(mio["user_id"]) == str(empleado["id"])


async def test_el_colaborador_no_llega_al_listado_de_todos(cliente, auth):
    assert (await cliente.get("/admin/papeles", headers=auth)).status_code == 403
