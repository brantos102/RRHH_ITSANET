"""El esquema MySQL: que exista todo, y que cada regla rechace lo que debe.

No basta con que una restricción se cree: tiene que rechazar el dato malo.
Cada prueba de rechazo comprueba además el NOMBRE de la restricción en el
error, porque es lo que la aplicación usa para decirle al usuario qué falló.
Un disparador que rechaza con otro nombre dejaría al usuario con «Los datos
enviados no cumplen una regla del sistema» en vez del mensaje correcto.
"""
from __future__ import annotations

import uuid

import pymysql
import pytest

from conftest import error_de

CEDULA_OK = "1710034065"        # válida
CEDULA_OTRA = "0926687856"      # válida
CEDULA_MALA = "1710034066"      # dígito verificador incorrecto


def nueva_persona(db, cedula=CEDULA_OK, **extra) -> str:
    pid = str(uuid.uuid4())
    campos = {"id": pid, "cedula": cedula, "nombre": "Persona de Prueba",
              "fecha_ingreso": "2020-01-15", **extra}
    cols = ", ".join(campos)
    marcas = ", ".join(["%s"] * len(campos))
    db.execute(f"INSERT INTO users ({cols}) VALUES ({marcas})", tuple(campos.values()))
    return pid


# ---------------------------------------------------------- que esté todo
def test_estan_las_38_tablas(db):
    db.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
                     AND table_name NOT IN ('schema_migraciones', 'secuencias')""")
    assert db.fetchone()["n"] == 38


def test_toda_la_base_esta_en_utf8mb4(db):
    """Una sola tabla en otro juego de caracteres corrompe sus tildes."""
    db.execute("""SELECT table_name, table_collation FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_collation <> 'utf8mb4_0900_ai_ci'""")
    assert list(db.fetchall()) == []


def test_los_datos_de_referencia_cargaron(db):
    esperado = {"regiones": 2, "ciudades_region": 55, "app_config": 25,
                "permission_types": 22, "legal_references": 37}
    for tabla, n in esperado.items():
        db.execute(f"SELECT COUNT(*) AS n FROM {tabla}")
        assert db.fetchone()["n"] == n, tabla


def test_un_texto_largo_entra_entero(db):
    """El mandato pasa de 255 caracteres. Con VARCHAR(255) se rechazaba."""
    db.execute("SELECT CHAR_LENGTH(valor) AS n FROM app_config WHERE clave = 'mandato_descripcion'")
    assert db.fetchone()["n"] > 255


# ------------------------------------------------------ tildes y mayúsculas
def test_las_tildes_se_guardan_y_se_encuentran(db):
    """Probado en esta migración: sin utf8mb4 «Suárez» se corrompe en silencio."""
    nueva_persona(db, nombre="Suárez Ñúñez José")
    db.execute("SELECT nombre FROM users WHERE nombre LIKE %s", ("%suarez nunez jose%",))
    fila = db.fetchone()
    assert fila is not None, "la búsqueda sin tildes no encontró a la persona"
    assert fila["nombre"] == "Suárez Ñúñez José", "el nombre se guardó corrompido"


def test_el_correo_choca_sin_importar_mayusculas(db):
    nueva_persona(db, email="jganchoso@itsanet.com")
    with pytest.raises(pymysql.err.IntegrityError) as e:
        nueva_persona(db, cedula=CEDULA_OTRA, email="JGanchoso@ITSANET.com")
    assert "users_email_key" in error_de(e)[1]


# ------------------------------------------------------------- la cédula
@pytest.mark.parametrize("cedula,valida", [
    ("1710034065", True), ("0926687856", True), ("3010034063", None),
    ("1710034066", False),   # dígito verificador
    ("2510034065", False),   # provincia 25 no existe
    ("1760034065", False),   # tercer dígito 6: no es persona natural
    ("171003406", False), ("17100340655", False), ("17100340a5", False), (None, False),
])
def test_la_cedula_se_valida_igual_que_en_python(db, cedula, valida):
    """La misma lógica que app/cedula.py: si una cambia, las dos."""
    sys_path_cedula()
    from app.cedula import es_cedula_valida as en_python
    db.execute("SELECT es_cedula_valida(%s) AS v", (cedula,))
    en_mysql = bool(db.fetchone()["v"])
    assert en_mysql == en_python(cedula or ""), cedula
    if valida is not None:
        assert en_mysql is valida, cedula


def sys_path_cedula():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


def test_una_cedula_mala_no_entra(db):
    with pytest.raises(pymysql.err.OperationalError) as e:
        nueva_persona(db, cedula=CEDULA_MALA)
    numero, texto = error_de(e)
    assert numero == 3819, "tiene que responder igual que un CHECK"
    assert "users_cedula_valida" in texto


def test_tampoco_al_corregirla(db):
    nueva_persona(db)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("UPDATE users SET cedula = %s WHERE cedula = %s", (CEDULA_MALA, CEDULA_OK))
    assert "users_cedula_valida" in error_de(e)[1]


# --------------------------------------- las que eran CHECK con foránea
def test_nadie_es_su_propio_jefe(db):
    pid = nueva_persona(db)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("UPDATE users SET jefe_id = id WHERE id = %s", (pid,))
    assert "users_no_es_su_propio_jefe" in error_de(e)[1]


def test_una_baja_lleva_motivo(db):
    pid = nueva_persona(db)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("UPDATE users SET activo = FALSE, fecha_salida = CURDATE() WHERE id = %s", (pid,))
    assert "users_salida_con_motivo" in error_de(e)[1]


def test_la_historia_sin_motivo_si_entra_al_trasladar(db):
    """Era NOT VALID en PostgreSQL: vale para lo nuevo, no para lo histórico."""
    pid = nueva_persona(db)
    db.execute("SET @migrando = 1")
    try:
        db.execute("UPDATE users SET activo = FALSE, fecha_salida = CURDATE() WHERE id = %s", (pid,))
    finally:
        db.execute("SET @migrando = NULL")
    db.execute("SELECT activo FROM users WHERE id = %s", (pid,))
    assert db.fetchone()["activo"] == 0


def test_el_reemplazo_no_es_el_solicitante(db):
    pid = nueva_persona(db)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("""INSERT INTO requests (id, user_id, tipo, fecha_inicio, fecha_fin,
                        descripcion, reemplazo_id, dias_solicitados, saldo_al_solicitar)
                      VALUES (UUID(), %s, 'vacacion', '2026-12-01', '2026-12-08',
                        'Descanso programado', %s, 8, 15)""", (pid, pid))
    assert "requests_reemplazo_distinto" in error_de(e)[1]


def test_un_permiso_nuevo_lleva_justificacion(db):
    pid = nueva_persona(db)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("""INSERT INTO requests (id, user_id, tipo, fecha_inicio, fecha_fin,
                        descripcion, permission_type_id, dias_solicitados, saldo_al_solicitar)
                      VALUES (UUID(), %s, 'permiso', '2026-12-01', '2026-12-01',
                        'Trámite personal', 1, 1, 15)""", (pid,))
    assert "requests_permiso_justificado" in error_de(e)[1]


# ----------------------------------------------------- la región
def test_la_region_sale_de_la_ciudad(db):
    pid = nueva_persona(db, ciudad="Guayaquil")
    db.execute("SELECT region FROM users WHERE id = %s", (pid,))
    assert db.fetchone()["region"] == "costa"


def test_aunque_el_alta_traiga_otra_region(db):
    """Como en PostgreSQL: al insertar, la ciudad manda."""
    pid = nueva_persona(db, ciudad="Guayaquil", region="sierra")
    db.execute("SELECT region FROM users WHERE id = %s", (pid,))
    assert db.fetchone()["region"] == "costa"


def test_cambiar_de_ciudad_cambia_la_region(db):
    pid = nueva_persona(db, ciudad="Quito")
    db.execute("UPDATE users SET ciudad = 'Guayaquil' WHERE id = %s", (pid,))
    db.execute("SELECT region FROM users WHERE id = %s", (pid,))
    assert db.fetchone()["region"] == "costa"


def test_una_ciudad_desconocida_va_a_la_sierra(db):
    pid = nueva_persona(db, ciudad="Ciudad Inventada")
    db.execute("SELECT region FROM users WHERE id = %s", (pid,))
    assert db.fetchone()["region"] == "sierra"


# --------------------------------------------- índices únicos parciales
def test_una_sola_constancia_de_goce_sin_autorizar(db):
    pid = nueva_persona(db)
    db.execute("""INSERT INTO informes_firmados (id, user_id, tipo, folio, datos)
                  VALUES (UUID(), %s, 'trazabilidad', 'TRZ-1', JSON_OBJECT())""", (pid,))
    with pytest.raises(pymysql.err.IntegrityError) as e:
        db.execute("""INSERT INTO informes_firmados (id, user_id, tipo, folio, datos)
                      VALUES (UUID(), %s, 'trazabilidad', 'TRZ-2', JSON_OBJECT())""", (pid,))
    assert "idx_trazabilidad_una_sola_vez" in error_de(e)[1]


def test_la_reemision_autorizada_si_entra(db):
    pid = nueva_persona(db)
    autoriza = nueva_persona(db, cedula=CEDULA_OTRA)
    db.execute("""INSERT INTO informes_firmados (id, user_id, tipo, folio, datos)
                  VALUES (UUID(), %s, 'trazabilidad', 'TRZ-1', JSON_OBJECT())""", (pid,))
    db.execute("""INSERT INTO informes_firmados (id, user_id, tipo, folio, datos,
                    autorizado_por, autorizado_en, autorizacion_motivo)
                  VALUES (UUID(), %s, 'trazabilidad', 'TRZ-2', JSON_OBJECT(),
                    %s, NOW(6), 'Extravió el ejemplar firmado en la bodega')""", (pid, autoriza))
    db.execute("SELECT COUNT(*) AS n FROM informes_firmados WHERE user_id = %s", (pid,))
    assert db.fetchone()["n"] == 2


def test_una_reemision_sin_motivo_no_entra(db):
    pid = nueva_persona(db)
    autoriza = nueva_persona(db, cedula=CEDULA_OTRA)
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("""INSERT INTO informes_firmados (id, user_id, tipo, folio, datos,
                        autorizado_por, autorizado_en)
                      VALUES (UUID(), %s, 'trazabilidad', 'TRZ-1', JSON_OBJECT(), %s, NOW(6))""",
                   (pid, autoriza))
    assert "informe_autorizacion_completa" in error_de(e)[1]


def test_un_solo_contacto_de_emergencia_principal(db):
    pid = nueva_persona(db)
    db.execute("""INSERT INTO emergency_contacts (id, user_id, nombre, telefono, parentesco, es_principal)
                  VALUES (UUID(), %s, 'Contacto Uno', '0991111111', 'conyuge', TRUE)""", (pid,))
    db.execute("""INSERT INTO emergency_contacts (id, user_id, nombre, telefono, parentesco, es_principal)
                  VALUES (UUID(), %s, 'Contacto Dos', '0992222222', 'conyuge', FALSE)""", (pid,))
    with pytest.raises(pymysql.err.IntegrityError) as e:
        db.execute("""INSERT INTO emergency_contacts (id, user_id, nombre, telefono, parentesco, es_principal)
                      VALUES (UUID(), %s, 'Contacto Tres', '0993333333', 'conyuge', TRUE)""", (pid,))
    assert "idx_emergency_principal" in error_de(e)[1]


# ------------------------------------------------------------ bitácoras
def test_la_bitacora_no_se_modifica(db):
    db.execute("INSERT INTO audit_logs (accion) VALUES ('prueba')")
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("UPDATE audit_logs SET accion = 'alterada'")
    assert "inmutables" in error_de(e)[1]


def test_la_bitacora_no_se_borra(db):
    db.execute("INSERT INTO audit_logs (accion) VALUES ('prueba')")
    with pytest.raises(pymysql.err.OperationalError):
        db.execute("DELETE FROM audit_logs")


def test_el_mensaje_de_la_bitacora_conserva_sus_tildes(db):
    """El texto del error sale de un disparador: también tiene que estar en utf8mb4."""
    db.execute("INSERT INTO audit_logs (accion) VALUES ('prueba')")
    with pytest.raises(pymysql.err.OperationalError) as e:
        db.execute("DELETE FROM audit_logs")
    assert "bitácoras" in error_de(e)[1] and "auditoría" in error_de(e)[1]


def test_la_depuracion_autorizada_si_puede(db):
    db.execute("INSERT INTO audit_logs (accion) VALUES ('prueba')")
    db.execute("SET @retencion = 'autorizada'")
    try:
        db.execute("DELETE FROM audit_logs WHERE accion = 'prueba'")
    finally:
        db.execute("SET @retencion = NULL")


# ---------------------------------------------- saldo y períodos
def test_el_saldo_de_la_ficha_es_la_suma_de_sus_periodos(db):
    pid = nueva_persona(db)
    for periodo, asignados, consumidos in ((1, 15, 10), (2, 15, 0)):
        db.execute("""INSERT INTO vacation_periods (id, user_id, periodo, fecha_desde, fecha_hasta,
                        dias_asignados, dias_consumidos, vence_en, devengado)
                      VALUES (UUID(), %s, %s, '2020-01-15', '2021-01-14', %s, %s, '2024-01-14', TRUE)""",
                   (pid, periodo, asignados, consumidos))
    db.execute("SELECT dias_vacaciones FROM users WHERE id = %s", (pid,))
    assert float(db.fetchone()["dias_vacaciones"]) == 20.0


def test_un_periodo_consumido_entero_tiene_sus_fines_de_semana_cumplidos(db):
    pid = nueva_persona(db)
    db.execute("""INSERT INTO vacation_periods (id, user_id, periodo, fecha_desde, fecha_hasta,
                    dias_asignados, dias_consumidos, vence_en, devengado,
                    fines_semana_obligatorios, fines_semana_consumidos)
                  VALUES (UUID(), %s, 1, '2020-01-15', '2021-01-14', 15, 15, '2024-01-14', TRUE, 2, 0)""",
               (pid,))
    db.execute("SELECT fines_semana_consumidos AS f FROM vacation_periods WHERE user_id = %s", (pid,))
    assert db.fetchone()["f"] == 2


def test_dias_saldo_es_una_columna_calculada(db):
    pid = nueva_persona(db)
    db.execute("""INSERT INTO vacation_periods (id, user_id, periodo, fecha_desde, fecha_hasta,
                    dias_asignados, dias_consumidos, vence_en, devengado)
                  VALUES (UUID(), %s, 1, '2020-01-15', '2021-01-14', 16.5, 4.25, '2024-01-14', TRUE)""",
               (pid,))
    db.execute("SELECT dias_saldo FROM vacation_periods WHERE user_id = %s", (pid,))
    assert str(db.fetchone()["dias_saldo"]) == "12.25"


# -------------------------------------------------------- el folio
def test_el_folio_de_la_solicitud_se_asigna_solo(db):
    pid = nueva_persona(db)
    folios = []
    for _ in range(2):
        db.execute("""INSERT INTO requests (id, user_id, tipo, fecha_inicio, fecha_fin, descripcion,
                        dias_solicitados, saldo_al_solicitar)
                      VALUES (UUID(), %s, 'vacacion', '2026-12-01', '2026-12-08',
                        'Descanso programado', 8, 15)""", (pid,))
        db.execute("SELECT LAST_INSERT_ID() AS f")
        folios.append(db.fetchone()["f"])
    assert folios[1] == folios[0] + 1
