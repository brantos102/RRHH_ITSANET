"""Por qué no sale el correo, dicho de forma que se pueda arreglar.

Cuando el envío del código falla, la pantalla dice «No pudimos enviar el
correo» —y tiene que decir eso, porque quien está entrando no es quien
configura el servidor—. El motivo real queda en el registro, dentro de una
traza de Python. Estas pruebas fijan la traducción de los fallos que de
verdad ocurren a lo que hay que hacer.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.correo import parametros_smtp

RAIZ = Path(__file__).resolve().parents[2]
GUION = RAIZ / "scripts" / "probar_correo.py"


def _cargar():
    sys.path.insert(0, str(RAIZ / "scripts"))
    especificacion = importlib.util.spec_from_file_location("probar_correo", GUION)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


probar = _cargar()


class Config:
    """Lo mínimo que mira el diagnóstico."""

    def __init__(self, **cambios):
        self.smtp_host = "smtp.gmail.com"
        self.smtp_port = 587
        self.smtp_user = "no-responder@itsanet.com.ec"
        self.smtp_password = "abcdefghijklmnop"
        self.smtp_starttls = True
        self.smtp_remitente = "Talento Humano <no-responder@itsanet.com.ec>"
        self.email_backend = "smtp"
        self.__dict__.update(cambios)


# ------------------------------------------------------- los fallos reales
def test_contrasena_normal_en_vez_de_contrasena_de_aplicacion():
    """Es el fallo número uno con Google Workspace."""
    error = Exception("(535, b'5.7.8 Username and Password not accepted')")
    texto = " ".join(probar.diagnostico(error, Config()))
    assert "aplicación" in texto.lower()
    assert "apppasswords" in texto


def test_puerto_bloqueado_por_la_red_de_la_oficina():
    error = TimeoutError("Connection timed out")
    lineas = probar.diagnostico(error, Config())
    texto = " ".join(lineas)
    assert "Test-NetConnection" in texto, "debe decir cómo comprobar el puerto"
    assert "EMAIL_BACKEND=console" in texto, "y cómo seguir probando mientras tanto"


def test_cifrado_que_no_cuadra_con_el_puerto():
    error = Exception("[SSL: WRONG_VERSION_NUMBER] wrong version number")
    texto = " ".join(probar.diagnostico(error, Config(smtp_port=465, smtp_starttls=True)))
    assert "587" in texto and "465" in texto


def test_nombre_de_servidor_mal_escrito():
    error = Exception("[Errno -2] Name or service not known")
    texto = " ".join(probar.diagnostico(error, Config(smtp_host="smpt.gmail.com")))
    assert "SMTP_HOST" in texto


def test_remitente_distinto_de_la_cuenta():
    error = Exception("(553, b'5.7.1 Relaying denied')")
    texto = " ".join(probar.diagnostico(error, Config()))
    assert "SMTP_REMITENTE" in texto


def test_un_fallo_desconocido_no_deja_sin_respuesta():
    texto = " ".join(probar.diagnostico(Exception("algo rarísimo"), Config()))
    assert "backend/.env" in texto
    assert "EMAIL_BACKEND=console" in texto


# ------------------------------------------------- lo que se ve sin conectar
def test_avisa_de_la_contrasena_con_espacios():
    """Google la muestra en cuatro grupos y se pega tal cual."""
    avisos = " ".join(probar.revisar(Config(smtp_password="abcd efgh ijkl mnop")))
    assert "espacios" in avisos


def test_avisa_de_la_contrasena_de_ejemplo_sin_reemplazar():
    avisos = " ".join(probar.revisar(Config(smtp_password="<contrasena_de_aplicacion>")))
    assert "ejemplo" in avisos


def test_avisa_de_que_en_modo_consola_nadie_recibe_nada():
    avisos = " ".join(probar.revisar(Config(email_backend="console")))
    assert "NO envía" in avisos


def test_avisa_del_587_sin_starttls():
    avisos = " ".join(probar.revisar(Config(smtp_port=587, smtp_starttls=False)))
    assert "587" in avisos


def test_una_configuracion_correcta_no_levanta_avisos():
    assert probar.revisar(Config()) == []


# ------------------------------------------------------ cómo se conecta
def test_el_587_sube_a_tls_con_starttls():
    parametros = parametros_smtp(Config(smtp_port=587, smtp_starttls=True))
    assert parametros["start_tls"] is True
    assert "use_tls" not in parametros


def test_el_465_nace_cifrado_y_no_lleva_starttls():
    """Pedir STARTTLS sobre una conexión ya cifrada deja el envío colgado."""
    parametros = parametros_smtp(Config(smtp_port=465, smtp_starttls=True))
    assert parametros["use_tls"] is True
    assert parametros["start_tls"] is False


def test_la_contrasena_vacia_se_manda_como_nula():
    """Cadena vacía y «sin usuario» no son lo mismo para el servidor."""
    parametros = parametros_smtp(Config(smtp_user="", smtp_password=""))
    assert parametros["username"] is None
    assert parametros["password"] is None


def test_el_guion_fija_la_politica_de_bucle_de_windows():
    assert "import _windows" in GUION.read_text(encoding="utf-8")
