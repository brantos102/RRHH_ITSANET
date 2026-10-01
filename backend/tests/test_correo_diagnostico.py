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

from app.correo import parametros_smtp, por_que_no_sale

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
    texto = " ".join(por_que_no_sale(error, Config()))
    assert "aplicación" in texto.lower()
    assert "apppasswords" in texto


def test_puerto_bloqueado_por_la_red_de_la_oficina():
    error = TimeoutError("Connection timed out")
    lineas = por_que_no_sale(error, Config())
    texto = " ".join(lineas)
    assert "Test-NetConnection" in texto, "debe decir cómo comprobar el puerto"
    assert "EMAIL_BACKEND=console" in texto, "y cómo seguir probando mientras tanto"


def test_cifrado_que_no_cuadra_con_el_puerto():
    error = Exception("[SSL: WRONG_VERSION_NUMBER] wrong version number")
    texto = " ".join(por_que_no_sale(error, Config(smtp_port=465, smtp_starttls=True)))
    assert "587" in texto and "465" in texto


def test_nombre_de_servidor_mal_escrito():
    error = Exception("[Errno -2] Name or service not known")
    texto = " ".join(por_que_no_sale(error, Config(smtp_host="smpt.gmail.com")))
    assert "SMTP_HOST" in texto


def test_remitente_distinto_de_la_cuenta():
    error = Exception("(553, b'5.7.1 Relaying denied')")
    texto = " ".join(por_que_no_sale(error, Config()))
    assert "SMTP_REMITENTE" in texto


def test_un_fallo_desconocido_no_deja_sin_respuesta():
    texto = " ".join(por_que_no_sale(Exception("algo rarísimo"), Config()))
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


def test_avisa_de_un_servidor_de_correo_en_la_propia_maquina():
    """Los cazadores de correo de desarrollo retienen los mensajes: usted ve
    su código y los colaboradores nunca reciben el suyo."""
    avisos = " ".join(probar.revisar(Config(smtp_host="localhost", smtp_port=1025)))
    assert "nadie los recibe" in avisos


def test_avisa_de_un_puerto_que_no_es_de_correo():
    avisos = " ".join(probar.revisar(Config(smtp_port=3000)))
    assert "3000" in avisos
    assert "dirección externa" in avisos


def test_los_puertos_de_correo_conocidos_no_levantan_aviso():
    for puerto, starttls in ((25, True), (587, True), (465, False), (2525, True)):
        avisos = probar.revisar(Config(smtp_port=puerto, smtp_starttls=starttls))
        assert avisos == [], f"puerto {puerto}: {avisos}"


# ------------------------------- el motivo queda bajo la misma referencia
async def test_el_registro_dice_el_motivo_bajo_la_referencia_de_la_pantalla(
    cliente, codigos, empleado, monkeypatch, caplog
):
    """La pantalla da una referencia; el registro, bajo ESA referencia, tiene
    que decir qué corregir. Antes dejaba una traza de treinta líneas, y con
    ella no se llega a ninguna parte."""
    import logging

    from app import correo as modulo_correo

    async def falla(*args, **kwargs):
        raise TimeoutError("Connection timed out")

    monkeypatch.setattr(modulo_correo, "enviar_otp", falla)

    with caplog.at_level(logging.ERROR, logger="rrhh.auth"):
        r = await cliente.post("/auth/solicitar-token",
                               json={"cedula": empleado["cedula"]})
    assert r.status_code == 503

    escrito = "\n".join(m.getMessage() for m in caplog.records)
    assert "no respondió a tiempo" in escrito, "no tradujo el fallo"
    assert "Test-NetConnection" in escrito, "no dice cómo comprobarlo"
    assert "EMAIL_BACKEND=console" in escrito, "no dice cómo seguir probando"


async def test_al_colaborador_se_le_sigue_diciendo_lo_justo(
    cliente, codigos, empleado, monkeypatch
):
    """Quien está entrando no puede abrir un puerto ni cambiar una clave."""
    from app import correo as modulo_correo

    async def falla(*args, **kwargs):
        raise TimeoutError("Connection timed out")

    monkeypatch.setattr(modulo_correo, "enviar_otp", falla)
    r = await cliente.post("/auth/solicitar-token", json={"cedula": empleado["cedula"]})

    cuerpo = r.text.lower()
    for filtracion in ("smtp", "contraseña de aplicación", "cortafuegos",
                       "test-netconnection", "gmail"):
        assert filtracion not in cuerpo, f"la pantalla filtra «{filtracion}»"


def test_el_guion_y_el_servidor_usan_la_misma_traduccion():
    """Dos copias de esto se desincronizan y una de las dos miente."""
    fuente = GUION.read_text(encoding="utf-8")
    assert "from app.correo import por_que_no_sale" in fuente
    assert "def diagnostico(" not in fuente, "el guion volvió a tener su propia copia"
