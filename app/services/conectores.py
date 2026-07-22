"""Registro dos conectores Composio e fábrica de clientes por serviço.

Cada serviço (Drive, Agenda, Gmail, Docs, Sheets, Meet) tem seu próprio auth
config no Composio (OAuth gerenciado). A identidade é sempre o ``escritorio_id``.
"""

import httpx

from app.config import Settings
from app.services.composio_drive import ComposioClient

# servico -> (nome exibido, toolkit slug, atributo do auth config em Settings)
CONECTORES: dict[str, tuple[str, str, str]] = {
    "drive": ("Google Drive", "googledrive", "COMPOSIO_GDRIVE_AUTH_CONFIG_ID"),
    "agenda": ("Google Agenda", "googlecalendar", "COMPOSIO_GCALENDAR_AUTH_CONFIG_ID"),
    "gmail": ("Gmail", "gmail", "COMPOSIO_GMAIL_AUTH_CONFIG_ID"),
    "docs": ("Google Docs", "googledocs", "COMPOSIO_GDOCS_AUTH_CONFIG_ID"),
    "sheets": ("Google Sheets", "googlesheets", "COMPOSIO_GSHEETS_AUTH_CONFIG_ID"),
    "meet": ("Google Meet", "googlemeet", "COMPOSIO_GMEET_AUTH_CONFIG_ID"),
}


def auth_config_de(settings: Settings, servico: str) -> str:
    """Auth config (ac_...) do serviço, ou string vazia se não configurado."""
    entrada = CONECTORES.get(servico)
    if entrada is None:
        return ""
    return getattr(settings, entrada[2], "") or ""


def client_para(settings: Settings, http: httpx.AsyncClient, servico: str) -> ComposioClient | None:
    """Monta o ComposioClient de um serviço, ou None se não estiver configurado."""
    if not settings.COMPOSIO_API_KEY:
        return None
    ac = auth_config_de(settings, servico)
    if not ac:
        return None
    return ComposioClient(
        http,
        api_key=settings.COMPOSIO_API_KEY,
        base_url=settings.COMPOSIO_BASE_URL,
        auth_config_id=ac,
    )


def nome_de(servico: str) -> str:
    """Nome exibível do serviço."""
    entrada = CONECTORES.get(servico)
    return entrada[0] if entrada else servico
