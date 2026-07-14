"""Configurações da aplicação via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variáveis de ambiente obrigatórias da aplicação.

    Carregadas do `.env` em desenvolvimento ou do ambiente em produção.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Supabase é opcional em modo demo — obrigatório quando ativar contas de assinantes
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    APP_ENV: Literal["development", "staging", "production"] = "development"
    SECRET_KEY: str = ""

    # W-API (WhatsApp)
    WAPI_BASE_URL: str = "https://api.w-api.app/v1"
    WAPI_TOKEN: str = ""
    WAPI_INSTANCE_ID: str = ""
    WAPI_API_KEY: str = ""

    # Mercado Pago (Pix para rifas)
    MERCADO_PAGO_ACCESS_TOKEN: str = ""
    MERCADO_PAGO_WEBHOOK_URL: str = ""
    ADMIN_TOKEN: str = ""  # Bearer simples para /admin/* até integrar Supabase Auth

    # Composio (conector do Google Drive dos escritórios — M3)
    COMPOSIO_API_KEY: str = ""
    COMPOSIO_GDRIVE_AUTH_CONFIG_ID: str = ""
    COMPOSIO_BASE_URL: str = "https://backend.composio.dev/api/v3"


@lru_cache
def get_settings() -> Settings:
    """Retorna as configurações da aplicação (cacheadas por processo)."""
    # Campos vêm do .env/ambiente em runtime — pyright não enxerga isso
    return Settings()  # pyright: ignore[reportCallIssue]
