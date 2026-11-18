"""La campana en vivo y el resumen diario de pendientes por correo."""
from __future__ import annotations

import datetime as dt

from app import correo
from app.db import ejecutar, obtener_uno
from app.reglas import resumen_pendientes
from tests.test_reglas_nuevas import auth, jefe_auth, rrhh_auth  # noqa: F401
from tests.test_respaldo_a_pedido import _permiso

LUNES = dt.date(2026, 11, 16)


async def test_la_consulta_liviana_cuenta_lo_sin_leer(cliente, auth, rrhh_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=44)
    await cliente.post(f"/aprobaciones/{creada['id']}/pedir-respaldo", headers=rrhh_auth,
                       json={"mensaje": "Adjunte la convocatoria del curso."})
    d = (await cliente.get("/auth/mis-notificaciones/nuevas", headers=auth)).json()
    assert d["sin_leer"] >= 1
    assert any(n["titulo"].startswith("Talento Humano pide el respaldo") for n in d["recientes"])
    await cliente.post("/auth/mis-notificaciones/leidas", headers=auth)
    assert (await cliente.get("/auth/mis-notificaciones/nuevas", headers=auth)).json()["sin_leer"] == 0


async def test_resumen_al_jefe_y_a_talento_humano_una_vez_al_dia(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    creada, _, _ = await _permiso(cliente, auth, semanas=45)
    await ejecutar("UPDATE requests SET created_at = NOW(6) - INTERVAL 3 DAY WHERE id = %s", (creada["id"],))
    enviados = []

    async def falso(destino, asunto, texto, html=None, **k):
        enviados.append((destino, asunto, texto))
    monkeypatch.setattr(correo, "enviar", falso)

    r = await resumen_pendientes.enviar_resumen(LUNES)
    al_jefe = [e for e in enviados if e[0] == "jefatura2@api.test"]
    assert al_jefe and "esperando su decisión" in al_jefe[0][1] and f"Nº {creada['folio']}" in al_jefe[0][2]
    a_th = [e for e in enviados if e[0] == "talento@api.test"]
    assert a_th and "atascada" in a_th[0][1] and f"Nº {creada['folio']}" in a_th[0][2]
    assert r["jefes"] >= 1 and r["talento_humano"] >= 1

    # Correrla otra vez el mismo día no repite nada.
    antes = len(enviados)
    await resumen_pendientes.enviar_resumen(LUNES)
    assert len(enviados) == antes
    await ejecutar("DELETE FROM notifications WHERE entidad = 'resumen'")


async def test_el_fin_de_semana_no_hay_resumen(monkeypatch):
    llamado = []

    async def falso(*a, **k):
        llamado.append(1)
    monkeypatch.setattr(correo, "enviar", falso)
    r = await resumen_pendientes.enviar_resumen(dt.date(2026, 11, 21))  # sábado
    assert r.get("omitido") == 1 and not llamado


async def test_una_reciente_no_entra_en_el_resumen_del_jefe(cliente, auth, jefe_auth, monkeypatch):
    creada, _, _ = await _permiso(cliente, auth, semanas=46)
    enviados = []

    async def falso(destino, asunto, texto, html=None, **k):
        enviados.append(texto)
    monkeypatch.setattr(correo, "enviar", falso)
    await resumen_pendientes.enviar_resumen(LUNES)
    assert not any(f"Nº {creada['folio']}:" in t for t in enviados)
    await ejecutar("DELETE FROM notifications WHERE entidad = 'resumen'")
    assert await obtener_uno("SELECT 1 AS x") is not None
