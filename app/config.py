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
    # Libera o hub (login, chat, APIs) para acesso externo. Local sempre tem
    # acesso total; em produção/deploy defina HUB_PUBLICO=true para os
    # assinantes acessarem. Falso (padrão) só expõe /proposta para fora.
    HUB_PUBLICO: bool = False

    # W-API (WhatsApp)
    WAPI_BASE_URL: str = "https://api.w-api.app/v1"
    WAPI_TOKEN: str = ""
    WAPI_INSTANCE_ID: str = ""
    WAPI_API_KEY: str = ""

    # Mercado Pago (Pix para rifas)
    MERCADO_PAGO_ACCESS_TOKEN: str = ""
    MERCADO_PAGO_PUBLIC_KEY: str = ""  # usado só se ativar o Payment Brick no front
    MERCADO_PAGO_WEBHOOK_URL: str = ""
    ADMIN_TOKEN: str = ""  # Bearer simples para /admin/* até integrar Supabase Auth

    # Composio (conectores dos escritórios via OAuth gerenciado)
    COMPOSIO_API_KEY: str = ""
    COMPOSIO_GDRIVE_AUTH_CONFIG_ID: str = ""
    COMPOSIO_BASE_URL: str = "https://backend.composio.dev/api/v3"
    # Pasta-raiz do acervo de modelos no Drive do escritório (vazio = grounding off)
    COMPOSIO_ACERVO_FOLDER_ID: str = ""
    # Auth configs (ac_...) dos demais toolkits Google — vazio = conector desligado.
    # Podem reusar a MESMA credencial OAuth do Google usada no Drive.
    COMPOSIO_GCALENDAR_AUTH_CONFIG_ID: str = ""
    COMPOSIO_GMAIL_AUTH_CONFIG_ID: str = ""
    COMPOSIO_GDOCS_AUTH_CONFIG_ID: str = ""
    COMPOSIO_GSHEETS_AUTH_CONFIG_ID: str = ""
    COMPOSIO_GMEET_AUTH_CONFIG_ID: str = ""


@lru_cache
def get_settings() -> Settings:
    """Retorna as configurações da aplicação (cacheadas por processo)."""
    # Campos vêm do .env/ambiente em runtime — pyright não enxerga isso
    return Settings()  # pyright: ignore[reportCallIssue]
