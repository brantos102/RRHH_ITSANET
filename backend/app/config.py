"""Configuración leída del entorno (12-factor)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # Aplicación
    app_nombre: str = "Sistema de Permisos y Vacaciones"
    app_url: str = "http://localhost:5500"
    cors_origins: str = "http://localhost:5500"
    entorno: str = "desarrollo"

    @property
    def origenes_permitidos(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def es_produccion(self) -> bool:
        return self.entorno.lower() in ("produccion", "production", "prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
