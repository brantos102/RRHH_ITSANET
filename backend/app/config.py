"""Configuración leída del entorno (12-factor)."""
import re
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# El .env vive junto al backend, y se busca por ruta absoluta: si se
# resolviera contra la carpeta actual, arrancar desde la raíz del proyecto
# (o desde cualquier otro sitio) daría «Field required: database_url» aunque
# el archivo estuviera ahí mismo. Las variables de entorno siguen mandando
# sobre el archivo, que es lo que esperan Docker y los servicios de hosting.
_CARPETA_BACKEND = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_CARPETA_BACKEND / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base de datos
    database_url: str

    # Supabase
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str

    # Sesión
    jwt_expira_horas: int = 8
    otp_longitud: int = 6
    otp_vigencia_minutos: int = 10
    otp_max_intentos: int = 5
    otp_max_envios_hora: int = 5

    # Correo
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_remitente: str = "Talento Humano <no-responder@localhost>"
    smtp_starttls: bool = True
    email_backend: str = "smtp"  # smtp | console

    # Enlaces de aprobación enviados por correo
    aprobacion_link_dias: int = 15

    # Aplicación
    app_nombre: str = "Sistema de Permisos y Vacaciones"
    app_url: str = "http://localhost:5500"
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"
    entorno: str = "desarrollo"

    # Registro de actividad
    nivel_log: str = "INFO"
    log_a_archivo: bool = True

    @property
    def origenes_permitidos(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def origen_regex(self) -> str | None:
        """Fuera de producción, cualquier puerto local o de la red interna.

        `localhost:5500` y `127.0.0.1:5500` son orígenes distintos para el
        navegador, y cada servidor de estáticos elige su propio puerto (Live
        Server usa 5500 o 5501, `python -m http.server` el que se le indique).
        Exigir que el puerto exacto esté en CORS_ORIGINS solo produce
        preflights rechazados con 400 durante el desarrollo.

        Y además las direcciones privadas de la red de la oficina. Para
        probar con colaboradores, el equipo de quien ejecuta el sistema
        atiende en `192.168.x.x` y los demás entran desde sus máquinas: ese
        origen no es `localhost` para sus navegadores, así que el preflight
        se rechazaba con un 400 y la pantalla solo decía «No se pudo
        conectar con el servidor». Son rangos que no existen en internet
        —RFC 1918—, así que esto no abre nada hacia afuera.

        En producción devuelve None: ahí manda la lista explícita y nada más.
        """
        if self.es_produccion:
            return None
        return (
            r"http://("
            r"localhost|127\.0\.0\.1|\[::1\]"
            r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"              # 10.0.0.0/8
            r"|192\.168\.\d{1,3}\.\d{1,3}"                  # 192.168.0.0/16
            r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"   # 172.16.0.0/12
            r"|[A-Za-z0-9-]+\.local"                           # nombres mDNS
            r"):\d+"
        )

    def origen_aceptado(self, origen: str) -> bool:
        """¿El navegador que envía este Origin recibirá respuesta?"""
        origen = origen.rstrip("/")
        if origen in self.origenes_permitidos:
            return True
        patron = self.origen_regex
        return bool(patron) and re.fullmatch(patron, origen) is not None

    @property
    def es_produccion(self) -> bool:
        return self.entorno.lower() in ("produccion", "production", "prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
