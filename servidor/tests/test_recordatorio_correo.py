"""El recordatorio al jefe sale por correo, con su propio asunto, y
Talento Humano ve en pantalla si salió o no.

Antes se mandaba en segundo plano el MISMO correo del aviso original: el
buzón lo juntaba en la conversación anterior (el jefe no veía nada nuevo) y,
si el servidor de correo fallaba, la pantalla decía igual «Se le recordó».
"""
from __future__ import annotations

from app import correo, notificaciones
from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import auth, jefe_auth, rrhh_auth  # noqa: F401
from tests.test_seguimiento_th import _crear


async def test_el_recordatorio_sale_con_su_asunto_y_enlace(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    vac, _ = await _crear(cliente, auth, 40)
    enviados = []

    async def falso(destino, asunto, texto, html=None, **k):
        enviados.append((destino, asunto, texto))
    monkeypatch.setattr(correo, "enviar", falso)

    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert r.json()["correo_enviado"] is True and "por correo" in r.json()["mensaje"]
    destino, asunto, texto = enviados[-1]
    assert destino == "jefatura2@api.test"
    assert asunto.startswith("Recordatorio:") and f"Nº {vac['folio']}" in asunto
    assert "aprobar.html?t=" in texto  # enlace directo, aún vigente
    # Queda constancia de que el correo salió.
    fila = await obtener_uno(
        """SELECT MAX(email_enviado_en) AS e FROM notifications
            WHERE entidad_id = %s AND tipo = 'solicitud_pendiente'""", (vac["id"],))
    assert fila["e"] is not None


async def test_con_el_enlace_vencido_lleva_al_sistema(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    vac, _ = await _crear(cliente, auth, 41)
    await ejecutar("UPDATE requests SET created_at = NOW(6) - INTERVAL 20 DAY WHERE id = %s", (vac["id"],))
    enviados = []

    async def falso(destino, asunto, texto, html=None, **k):
        enviados.append(texto)
    monkeypatch.setattr(correo, "enviar", falso)
    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200
    assert "dashboard.html#aprobaciones" in enviados[-1] and "aprobar.html" not in enviados[-1]


async def test_si_el_correo_falla_talento_humano_lo_ve(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    vac, _ = await _crear(cliente, auth, 42)

    async def falla(*a, **k):
        raise TimeoutError("Timed out connecting to pro.turbo-smtp.com on port 587")
    monkeypatch.setattr(correo, "enviar", falla)
    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200
    assert r.json()["correo_enviado"] is False and "NO salió" in r.json()["mensaje"]
    # El aviso en el sistema sí quedó, y el fallo en la bitácora.
    assert await obtener_uno(
        """SELECT 1 AS x FROM notifications WHERE entidad_id = %s AND titulo LIKE 'Recordatorio:%%'""",
        (vac["id"],))
    assert await obtener_uno(
        "SELECT 1 AS x FROM audit_logs WHERE accion = 'recordatorio_correo_fallido' AND entidad_id = %s",
        (vac["id"],))


async def test_jefe_sin_correo_se_dice_claro(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    vac, _ = await _crear(cliente, auth, 43)
    await ejecutar("UPDATE users SET email = NULL WHERE cedula = '0900000001'")
    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200
    assert r.json()["correo_enviado"] is None and "no tiene correo" in r.json()["mensaje"]


def test_el_asunto_no_repite_el_del_aviso_original():
    """Si fueran iguales, el buzón los junta y el recordatorio pasa inadvertido."""
    import inspect
    assert "Recordatorio:" in inspect.getsource(notificaciones.recordar_al_jefe)
