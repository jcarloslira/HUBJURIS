"""Dependências FastAPI da integração com o Google Drive (via Composio)."""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.services.composio_drive import ComposioClient

# Single-tenant no MVP: um escritório fixo. Vira o escritorio_id quando SaaS.
USER_ID_PADRAO = "escritorio-1"


def get_composio_client(
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> ComposioClient | None:
    """Cria o cliente Composio a partir das settings, ou None se não configurado."""
    if not settings.COMPOSIO_API_KEY or not settings.COMPOSIO_GDRIVE_AUTH_CONFIG_ID:
        return None
    return ComposioClient(
        request.app.state.http_client,
        api_key=settings.COMPOSIO_API_KEY,
        base_url=settings.COMPOSIO_BASE_URL,
        auth_config_id=settings.COMPOSIO_GDRIVE_AUTH_CONFIG_ID,
    )
