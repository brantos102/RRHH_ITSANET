"""Por qué no se guarda el respaldo de un permiso.

Es el fallo que más desconcierta de todos los posibles, porque el mensaje
—«No se pudo guardar el archivo. Intente de nuevo.»— sugiere que el archivo
tiene algo malo. El colaborador prueba con otra imagen, luego con un PDF, y
falla igual: el archivo nunca fue el problema.

La causa real casi siempre es que el bucket de Supabase Storage no existe
—las migraciones crean las tablas, no los buckets— o que la clave
configurada es la «anon» y no la «service_role».
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.storage import por_que_fallo

RAIZ = Path(__file__).resolve().parents[2]
GUION = RAIZ / "scripts" / "probar_adjuntos.py"


def _cargar():
    sys.path.insert(0, str(RAIZ / "scripts"))
    especificacion = importlib.util.spec_from_file_location("probar_adjuntos", GUION)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


probar = _cargar()


# --------------------------------------------------- la traducción del fallo
def test_el_bucket_que_no_existe_dice_como_crearlo():
    """Es la causa número uno en una instalación nueva."""
    texto = por_que_fallo(400, '{"statusCode":"404","error":"Bucket not found"}')
    assert "no existe" in texto
    assert "probar_adjuntos.py --crear" in texto


def test_la_clave_anon_en_vez_de_la_service_role():
    texto = por_que_fallo(401, '{"message":"Invalid JWT"}')
    assert "service_role" in texto
    assert "anon" in texto


def test_una_politica_que_bloquea_la_escritura():
    texto = por_que_fallo(400, "new row violates row-level security policy")
    assert "service_role" in texto


def test_el_archivo_que_supera_el_limite_del_bucket():
    texto = por_que_fallo(413, "Payload too large")
    assert "límite" in texto


def test_un_tipo_de_archivo_que_el_bucket_no_admite():
    texto = por_que_fallo(400, '{"error":"mime type application/pdf is not supported"}')
    assert "MIME" in texto


def test_un_fallo_desconocido_no_deja_sin_salida():
    texto = por_que_fallo(418, "algo rarísimo")
    assert "probar_adjuntos.py" in texto


# ------------------------------------------------- el guion de diagnóstico
def test_el_guion_conoce_los_buckets_que_el_sistema_usa():
    assert set(probar.BUCKETS) == {"solicitudes", "firmas"}


def test_los_buckets_se_crean_privados():
    """Un certificado médico en un bucket público es una URL que cualquiera
    puede abrir. Es dato de salud (LOPDP)."""
    fuente = GUION.read_text(encoding="utf-8")
    assert '"public": False' in fuente
    assert "public.*True" not in fuente


# Tres causas, un solo síntoma en pantalla. Decir «es la anon» cuando la
# clave ni siquiera es un JWT manda a buscar donde no es: fue exactamente lo
# que pasó la primera vez que esto se usó contra el proyecto real.
def test_una_clave_cortada_no_se_confunde_con_la_anon():
    """41 caracteres y ningún punto: eso no es ninguna clave de Supabase."""
    avisos = " ".join(probar.revisar_clave("x" * 35 + "fa8RLb"))
    assert "no tiene forma de JWT" in avisos
    assert "41 caracteres" in avisos
    assert "cortada" in avisos
    assert "anon" not in avisos, "no debe culpar a la clave anon"


def test_el_formato_nuevo_de_supabase_se_reconoce():
    """`sb_secret_…` es una clave legítima; Storage todavía espera la clásica."""
    avisos = " ".join(probar.revisar_clave("sb_secret_" + "a" * 31))
    assert "formato nuevo" in avisos
    assert "Legacy API keys" in avisos


def test_la_clave_anon_si_se_señala_como_tal():
    import base64
    import json

    cuerpo = base64.urlsafe_b64encode(json.dumps({"role": "anon"}).encode()).decode().rstrip("=")
    avisos = " ".join(probar.revisar_clave(f"eyJhbGciOiJIUzI1NiJ9.{cuerpo}.{'f' * 43}"))
    assert "anon" in avisos
    assert "service_role" in avisos


def test_la_clave_correcta_no_levanta_ningun_aviso():
    import base64
    import json

    cuerpo = base64.urlsafe_b64encode(
        json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
    assert probar.revisar_clave(f"eyJhbGciOiJIUzI1NiJ9.{cuerpo}.{'f' * 43}") == []


def test_invalid_compact_jws_no_culpa_a_la_clave_anon():
    """Es el error exacto que devolvió Supabase: la clave no es un JWT."""
    texto = por_que_fallo(400, '{"statusCode":"403","error":"Unauthorized",'
                               '"message":"Invalid Compact JWS","code":"AccessDenied"}')
    assert "no tiene forma de clave" in texto
    assert "sb_secret_" in texto
    assert "cortada" in texto


def test_distingue_la_clave_anon_de_la_service_role():
    """El cuerpo del JWT va en claro: basta mirarlo, sin descifrar nada."""
    import base64
    import json

    def jwt_falso(rol: str) -> str:
        cuerpo = base64.urlsafe_b64encode(
            json.dumps({"role": rol}).encode()).decode().rstrip("=")
        return f"cabecera.{cuerpo}.firma"

    assert "service_role" in probar._cuerpo_del_jwt(jwt_falso("service_role"))
    assert "service_role" not in probar._cuerpo_del_jwt(jwt_falso("anon"))


def test_una_clave_que_no_es_un_jwt_no_revienta():
    assert probar._cuerpo_del_jwt("esto-no-es-un-jwt") == "esto-no-es-un-jwt"


def test_el_guion_fija_la_politica_de_bucle_de_windows():
    assert "import _windows" in GUION.read_text(encoding="utf-8")


# ------------------------------------------------------ lo que ve el usuario
def test_el_colaborador_nunca_ve_el_detalle_tecnico():
    """El mensaje de la pantalla no puede nombrar buckets ni claves: quien
    adjunta un certificado no puede arreglar ninguna de las dos cosas."""
    import inspect

    from app import storage
    fuente = inspect.getsource(storage.subir)
    i = fuente.index('detail={"mensaje"')
    mensaje = fuente[i:i + 160]
    for filtracion in ("bucket", "service_role", "supabase", "JWT"):
        assert filtracion.lower() not in mensaje.lower(), filtracion
