"""Los documentos firmados en Python, comparados con PostgreSQL en la muestra."""
from __future__ import annotations

import re

from app.db import obtener_todos, obtener_uno
from app.reglas import papeles
from diferencial import json_normal, muestra, y_deshacer  # noqa: F401

COLUMNAS = ["user_id", "tipo", "request_id", "autorizado_por", "autorizacion_motivo",
            "emitido_por", "datos", "impresiones"]


def _fila(f):
    return json_normal({c: f[c] for c in COLUMNAS})


def _ordenadas(filas):
    """La muestra se generó en una sola transacción de PostgreSQL: sus
    documentos comparten la hora de emisión y ese orden no dice nada."""
    return sorted(filas, key=lambda f: (f["tipo"], f["request_id"] or "", f["autorizado_por"] or ""))


async def test_datos_de_trazabilidad_de_toda_la_muestra(muestra):
    for p in muestra.execute("select id from users order by cedula").fetchall():
        en_pg = muestra.execute("select datos_informe_trazabilidad(%s) as d", (p["id"],)).fetchone()["d"]
        assert json_normal(await papeles.datos_informe_trazabilidad(p["id"])) == json_normal(en_pg), p["id"]


async def test_datos_de_cada_solicitud_de_la_muestra(muestra):
    filas = muestra.execute("select id from requests order by folio").fetchall()
    assert len(filas) > 40
    for r in filas:
        en_pg = muestra.execute("select datos_informe_solicitud(%s) as d", (r["id"],)).fetchone()["d"]
        assert json_normal(await papeles.datos_informe_solicitud(r["id"])) == json_normal(en_pg), r["id"]


async def test_el_folio_tiene_la_forma_de_siempre_y_no_se_repite():
    async with y_deshacer():
        a = await papeles.folio_informe("trazabilidad")
        b = await papeles.folio_informe("solicitud")
    assert re.fullmatch(r"TRZ-\d{4}-\d{5}", a) and re.fullmatch(r"SOL-\d{4}-\d{5}", b)
    assert int(b[-5:]) == int(a[-5:]) + 1


async def test_asegurar_la_trazabilidad_de_quien_no_la_tiene(muestra):
    sin = muestra.execute("""select u.id from users u where not exists
                               (select 1 from informes_firmados i where i.user_id = u.id)
                             order by cedula limit 5""").fetchall()
    assert sin
    with muestra.transaction(force_rollback=True):
        for p in sin:
            muestra.execute("select informe_trazabilidad_asegurar(%s, null)", (p["id"],))
        en_pg = [_fila(f) for f in muestra.execute(
            "select * from informes_firmados where user_id = any(%s) order by user_id",
            ([p["id"] for p in sin],)).fetchall()]
    async with y_deshacer():
        for p in sin:
            await papeles.informe_trazabilidad_asegurar(p["id"])
            # La segunda vez devuelve el mismo: se emite una sola vez.
            await papeles.informe_trazabilidad_asegurar(p["id"])
        en_my = [_fila(f) for f in await obtener_todos(
            "SELECT * FROM informes_firmados WHERE user_id IN %s ORDER BY user_id",
            (tuple(str(p["id"]) for p in sin),))]
    assert en_my == en_pg


async def test_asegurar_el_de_una_solicitud_lo_actualiza(muestra):
    r = muestra.execute("""select i.request_id from informes_firmados i
                            where i.tipo = 'solicitud' order by folio limit 1""").fetchone()
    with muestra.transaction(force_rollback=True):
        muestra.execute("update requests set descripcion = 'Cambiada en la prueba' where id = %s",
                        (r["request_id"],))
        muestra.execute("select informe_solicitud_asegurar(%s, null)", (r["request_id"],))
        en_pg = _fila(muestra.execute("select * from informes_firmados where request_id = %s",
                                      (r["request_id"],)).fetchone())
    async with y_deshacer():
        from app.db import ejecutar
        await ejecutar("UPDATE requests SET descripcion = 'Cambiada en la prueba' WHERE id = %s",
                       (r["request_id"],))
        await papeles.informe_solicitud_asegurar(r["request_id"])
        en_my = _fila(await obtener_uno("SELECT * FROM informes_firmados WHERE request_id = %s",
                                        (r["request_id"],)))
    assert en_my == en_pg
    assert en_my["datos"]["solicitud"]["descripcion"] == "Cambiada en la prueba"


async def test_reemitir_y_sus_rechazos(muestra):
    rrhh = muestra.execute("select id from users where rol = 'rrhh' limit 1").fetchone()["id"]
    con = muestra.execute("select user_id from informes_firmados where tipo = 'trazabilidad' "
                          "order by folio limit 1").fetchone()["user_id"]
    sin = muestra.execute("""select u.id from users u where not exists
                               (select 1 from informes_firmados i where i.user_id = u.id)
                             limit 1""").fetchone()["id"]
    for persona, motivo in [(con, "   "), (sin, "Se perdió el original"), (con, "Se perdió el original")]:
        with muestra.transaction(force_rollback=True):
            try:
                muestra.execute("select informe_trazabilidad_reemitir(%s, %s, %s)", (persona, rrhh, motivo))
                err_pg = None
                en_pg = [_fila(f) for f in muestra.execute(
                    "select * from informes_firmados where user_id = %s order by emitido_en", (persona,))]
            except Exception as exc:  # noqa: BLE001
                err_pg = exc.diag.message_primary
        async with y_deshacer():
            try:
                await papeles.informe_trazabilidad_reemitir(persona, rrhh, motivo)
                err_my = None
                en_my = [_fila(f) for f in await obtener_todos(
                    "SELECT * FROM informes_firmados WHERE user_id = %s ORDER BY emitido_en", (persona,))]
            except Exception as exc:  # noqa: BLE001
                err_my = exc.mensaje
        assert err_my == err_pg
        if err_pg is None:
            assert _ordenadas(en_my) == _ordenadas(en_pg)


async def test_imprimir_cuenta_las_impresiones():
    async with y_deshacer():
        i = await obtener_uno("SELECT id, impresiones FROM informes_firmados LIMIT 1")
        await papeles.informe_impreso(i["id"])
        await papeles.informe_impreso(i["id"])
        despues = await obtener_uno("SELECT impresiones, ultima_impresion FROM informes_firmados WHERE id = %s",
                                    (i["id"],))
    assert despues["impresiones"] == i["impresiones"] + 2 and despues["ultima_impresion"] is not None
