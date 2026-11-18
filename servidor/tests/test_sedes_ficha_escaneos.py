"""Sedes y regiones, discapacidad, tipo de contrato, foto, escaneos firmados
y devengo diario.

Lo que vigilan estas pruebas:
  · una sede nueva se crea desde el sistema, y pasar una ciudad a ella
    cambia de sede a quienes viven ahí;
  · la discapacidad la declara la persona y rige cuando Talento Humano la
    aprueba, con el porcentaje junto (la base exige porcentaje si hay
    discapacidad);
  · el tipo de contrato se ve en Mi ficha pero no lo cambia la persona;
  · la foto se recodifica sin metadatos y solo la ven quien corresponde;
  · el escaneo firmado se guarda con su huella, no se reemplaza sin motivo y
    no lo ve un tercero;
  · la tarea diaria pone al día el devengo de toda la planilla.
"""
from __future__ import annotations

import io
from datetime import timedelta

import pytest
from PIL import Image

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados, rrhh_auth)

SEDE = "cuenca_prueba"


@pytest.fixture
async def sin_sede_de_prueba(empleado):
    yield
    await ejecutar("UPDATE users SET ciudad = NULL, region = 'sierra' WHERE region = %s", (SEDE,))
    await ejecutar("UPDATE requests SET region = 'sierra' WHERE region = %s", (SEDE,))
    await ejecutar("DELETE FROM firmantes_rrhh WHERE region = %s", (SEDE,))
    await ejecutar("DELETE FROM ciudades_region WHERE region = %s OR ciudad = 'PRUEBALANDIA'", (SEDE,))
    await ejecutar("DELETE FROM regiones WHERE codigo = %s", (SEDE,))
    await ejecutar("DELETE FROM app_config WHERE clave = %s", (f"rrhh_correo_{SEDE}",))


# ------------------------------------------------------------------ sedes
async def test_catalogo_de_sedes_para_cualquiera(cliente, auth):
    r = await cliente.get("/catalogos/sedes", headers=auth)
    assert r.status_code == 200
    codigos = {s["codigo"] for s in r.json()}
    assert {"sierra", "costa"} <= codigos
    quito = next(s for s in r.json() if s["codigo"] == "sierra")
    assert quito["sede"] == "Quito" and "amazonia" in quito["regiones_naturales"]


async def test_colaborador_no_administra_sedes(cliente, auth):
    assert (await cliente.get("/admin/sedes", headers=auth)).status_code == 403
    r = await cliente.post("/admin/sedes", headers=auth, json={"sede": "Cuenca Prueba"})
    assert r.status_code == 403


async def test_sede_nueva_y_ciudad_que_pasa_a_ella(cliente, rrhh_auth, empleado, sin_sede_de_prueba):
    # Una ciudad que no está registrada: queda en Quito sin que nadie lo decida.
    await ejecutar("UPDATE users SET ciudad = 'Pruebalandia' WHERE id = %s", (empleado["id"],))
    assert (await obtener_uno("SELECT region FROM users WHERE id = %s", (empleado["id"],)))["region"] == "sierra"
    resumen = (await cliente.get("/admin/sedes", headers=rrhh_auth)).json()
    assert any(c["ciudad"] == "Pruebalandia" for c in resumen["sin_ciudad"])

    r = await cliente.post("/admin/sedes", headers=rrhh_auth, json={
        "sede": "Cuenca Prueba", "nombre": "Austro", "regiones_naturales": ["sierra", "amazonia"]})
    assert r.status_code == 201, r.text
    assert r.json()["codigo"] == SEDE
    # La ciudad de la sede queda registrada y atendida por ella.
    assert (await obtener_uno("SELECT region FROM ciudades_region WHERE ciudad = 'CUENCA PRUEBA'"))["region"] == SEDE

    r = await cliente.post("/admin/ciudades", headers=rrhh_auth, json={
        "ciudad": "pruebalandia", "region": SEDE, "provincia": "Azuay", "region_natural": "sierra"})
    assert r.status_code == 200, r.text
    assert r.json()["personas"] == 1
    assert (await obtener_uno("SELECT region FROM users WHERE id = %s", (empleado["id"],)))["region"] == SEDE

    # Atiende ciudades y personas: no se puede desactivar así nomás.
    r = await cliente.patch(f"/admin/sedes/{SEDE}", headers=rrhh_auth, json={"activo": False})
    assert r.status_code == 422 and "ciudad" in r.json()["detail"]["mensaje"]
    # Con gente viviendo ahí, la ciudad no se quita.
    r = await cliente.delete("/admin/ciudades/PRUEBALANDIA", headers=rrhh_auth)
    assert r.status_code == 422

    # La sede nueva vale para firmantes y para la ficha.
    r = await cliente.patch(f"/admin/usuarios/{empleado['id']}", headers=rrhh_auth,
                            json={"region": "inexistente"})
    assert r.status_code == 422


async def test_consulta_del_chat_a_una_sede_que_no_existe(cliente, auth):
    r = await cliente.post("/chat/mensajes", headers=auth, json={
        "texto": "Hola", "asunto": "Prueba", "region": "marte"})
    assert r.status_code == 422


# ----------------------------------------------------------- discapacidad
async def test_discapacidad_se_declara_y_rige_al_aprobarla(cliente, auth, rrhh_auth, empleado):
    r = await cliente.post("/mi-ficha/discapacidad", headers=auth, json={"tiene": True})
    assert r.status_code == 422

    r = await cliente.post("/mi-ficha/discapacidad", headers=auth, json={
        "tiene": True, "porcentaje": 40, "tipo": "fisica", "carnet": "09-12345"})
    assert r.status_code == 201, r.text
    pedidos = {c["campo"]: c for c in await obtener_todos(
        "SELECT id, campo, valor_nuevo FROM cambios_ficha WHERE user_id = %s AND estado = 'pendiente'",
        (empleado["id"],))}
    assert {"tiene_discapacidad", "porcentaje_discapacidad", "carnet_conadis",
            "tipo_discapacidad"} <= set(pedidos)
    # Mientras no se aprueba, no rige.
    assert not (await obtener_uno("SELECT tiene_discapacidad FROM users WHERE id = %s",
                                  (empleado["id"],)))["tiene_discapacidad"]

    # Se aprueba el «sí» primero: el porcentaje entra con él.
    r = await cliente.post(f"/rrhh/cambios-ficha/{pedidos['tiene_discapacidad']['id']}",
                           headers=rrhh_auth, json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    u = await obtener_uno("SELECT tiene_discapacidad, porcentaje_discapacidad FROM users WHERE id = %s",
                          (empleado["id"],))
    assert u["tiene_discapacidad"] and u["porcentaje_discapacidad"] == 40
    estado = await obtener_uno("SELECT estado FROM cambios_ficha WHERE id = %s",
                               (pedidos["porcentaje_discapacidad"]["id"],))
    assert estado["estado"] == "aprobado"
    await ejecutar("DELETE FROM cambios_ficha WHERE user_id = %s", (empleado["id"],))


async def test_jefe_no_ve_datos_de_discapacidad(cliente, jefe_auth, empleado):
    await ejecutar("UPDATE users SET tiene_discapacidad = TRUE, porcentaje_discapacidad = 35 WHERE id = %s",
                   (empleado["id"],))
    r = await cliente.get(f"/personas/{empleado['id']}", headers=jefe_auth)
    assert r.status_code == 200
    assert r.json()["ficha"] is None
    assert "discapacidad" not in r.text


# ------------------------------------------------------- tipo de contrato
async def test_contrato_lo_registra_talento_humano_y_la_persona_lo_ve(cliente, auth, rrhh_auth, empleado):
    r = await cliente.patch(f"/admin/usuarios/{empleado['id']}", headers=rrhh_auth,
                            json={"tipo_contrato": "indefinido", "tipo_sangre": "O+"})
    assert r.status_code == 200, r.text
    ficha = (await cliente.get("/mi-ficha", headers=auth)).json()
    assert ficha["persona"]["tipo_contrato"] == "indefinido"
    nivel = {c["campo"]: c["nivel"] for c in ficha["campos"]}
    assert nivel["tipo_contrato"] == "bloqueado"
    r = await cliente.post("/mi-ficha/cambios", headers=auth,
                           json={"campo": "tipo_contrato", "valor": "eventual"})
    assert r.status_code == 422


# ------------------------------------------------------------------- foto
def _jpeg_con_gps() -> bytes:
    img = Image.new("RGB", (1200, 800), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "Telefono de prueba"           # Make
    exif[0x8825] = {1: "S", 2: (0.0, 13.0, 0.0)}  # GPSInfo
    salida = io.BytesIO()
    img.save(salida, "JPEG", exif=exif)
    return salida.getvalue()


async def test_foto_se_recodifica_sin_metadatos(cliente, auth, jefe_auth, empleado):
    original = _jpeg_con_gps()
    assert b"Telefono de prueba" in original
    r = await cliente.post("/mi-ficha/foto", headers=auth,
                           files={"archivo": ("yo.jpg", original, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert (await cliente.get("/auth/me", headers=auth)).json()["tiene_foto"] is True

    r = await cliente.get("/mi-ficha/foto", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert b"Telefono de prueba" not in r.content
    with Image.open(io.BytesIO(r.content)) as img:
        assert img.size == (512, 512)
        assert not img.getexif()

    # Su jefe la ve; nadie más fuera de Talento Humano.
    assert (await cliente.get(f"/personas/{empleado['id']}/foto", headers=jefe_auth)).status_code == 200
    await ejecutar("UPDATE users SET jefe_id = NULL WHERE id = %s", (empleado["id"],))
    assert (await cliente.get(f"/personas/{empleado['id']}/foto", headers=jefe_auth)).status_code == 404

    assert (await cliente.delete("/mi-ficha/foto", headers=auth)).status_code == 200
    assert (await cliente.get("/mi-ficha/foto", headers=auth)).status_code == 404


async def test_foto_que_no_es_imagen(cliente, auth):
    r = await cliente.post("/mi-ficha/foto", headers=auth,
                           files={"archivo": ("x.png", b"esto no es una imagen", "image/png")})
    assert r.status_code == 422


async def test_foto_url_ya_no_se_escribe_a_mano(cliente, auth):
    r = await cliente.patch("/mi-ficha", headers=auth, json={"foto_url": "../../etc/passwd"})
    assert r.status_code == 422


# ------------------------------------------------------- escaneo firmado
async def _papel_de_solicitud(cliente, auth, empleado) -> dict:
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Descanso programado con la familia", "firmar": False})
    assert r.status_code == 201, r.text
    return await obtener_uno(
        "SELECT id, folio FROM informes_firmados WHERE user_id = %s AND tipo = 'solicitud'",
        (empleado["id"],))


async def test_escaneo_firmado_con_huella_y_reemplazo_con_motivo(cliente, auth, rrhh_auth,
                                                                 jefe_auth, empleado):
    await ejecutar("DELETE FROM informes_firmados WHERE user_id = %s", (empleado["id"],))
    papel = await _papel_de_solicitud(cliente, auth, empleado)
    pdf = b"%PDF-1.4\n% documento firmado de prueba\n%%EOF\n"

    r = await cliente.post(f"/admin/papeles/{papel['id']}/escaneo", headers=rrhh_auth,
                           files={"archivo": ("firmado.pdf", b"no soy pdf", "application/pdf")})
    assert r.status_code == 422

    r = await cliente.post(f"/admin/papeles/{papel['id']}/escaneo", headers=rrhh_auth,
                           files={"archivo": ("firmado.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    import hashlib
    assert r.json()["sha256"] == hashlib.sha256(pdf).hexdigest()
    fila = await obtener_uno("SELECT firmado_en, escaneo_sha256 FROM informes_firmados WHERE id = %s",
                             (papel["id"],))
    assert fila["firmado_en"] is not None    # subir el escaneo registra la firma

    # Lo ve el dueño, íntegro; no lo ve su jefe.
    r = await cliente.get(f"/papeles/{papel['id']}/escaneo", headers=auth)
    assert r.status_code == 200 and r.content == pdf and r.headers["x-integridad"] == "ok"
    assert (await cliente.get(f"/papeles/{papel['id']}/escaneo", headers=jefe_auth)).status_code == 404

    # Reemplazar exige motivo.
    otro = b"%PDF-1.4\n% segunda version\n%%EOF\n"
    r = await cliente.post(f"/admin/papeles/{papel['id']}/escaneo", headers=rrhh_auth,
                           files={"archivo": ("firmado.pdf", otro, "application/pdf")})
    assert r.status_code == 409
    r = await cliente.post(f"/admin/papeles/{papel['id']}/escaneo", headers=rrhh_auth,
                           data={"motivo_reemplazo": "La primera hoja salió cortada"},
                           files={"archivo": ("firmado.pdf", otro, "application/pdf")})
    assert r.status_code == 200, r.text

    lista = (await cliente.get("/admin/papeles", headers=rrhh_auth, params={"q": papel["folio"]})).json()
    assert any(p["tiene_escaneo"] is True for p in lista)
    await ejecutar("DELETE FROM informes_firmados WHERE user_id = %s", (empleado["id"],))


# ----------------------------------------------------------- devengo diario
async def test_tarea_diaria_pone_al_dia_el_devengo(empleado):
    from app.reglas import tareas
    await ejecutar("UPDATE vacation_periods SET dias_asignados = 0 WHERE user_id = %s AND NOT devengado",
                   (empleado["id"],))
    resultado = await tareas.tarea_diaria()
    assert resultado["devengo"]["personas"] >= 1
    en_curso = await obtener_uno(
        """SELECT dias_asignados, dias_devengados_en_curso(u.fecha_ingreso, p.periodo) AS esperado
             FROM vacation_periods p JOIN users u ON u.id = p.user_id
            WHERE p.user_id = %s AND NOT p.devengado""", (empleado["id"],))
    assert en_curso["dias_asignados"] == en_curso["esperado"]
