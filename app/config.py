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

    # Evolution API (WhatsApp)
    EVOLUTION_API_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""


@lru_cache
def get_settings() -> Settings:
    """Retorna as configurações da aplicação (cacheadas por processo)."""
    # Campos vêm do .env/ambiente em runtime — pyright não enxerga isso
    return Settings()  # pyright: ignore[reportCallIssue]
