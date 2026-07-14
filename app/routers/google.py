"""Router da conexão do Google Drive do escritório (via Composio)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies_condominios import require_admin
from app.dependencies_google import USER_ID_PADRAO, get_composio_client
from app.services.composio_drive import ComposioClient

router = APIRouter(prefix="/api/google", tags=["google"], dependencies=[Depends(require_admin)])

_Client = Annotated[ComposioClient | None, Depends(get_composio_client)]


@router.get("/status", status_code=200)
async def status_conexao(client: _Client) -> dict[str, bool]:
    """Diz se o Composio está configurado e se há Drive conectado."""
    if client is None:
        return {"configurado": False, "conectado": False}
    conectado = await client.conexao_ativa(USER_ID_PADRAO)
    return {"configurado": True, "conectado": conectado}


@router.post("/conectar", status_code=200)
async def conectar(client: _Client) -> dict[str, str]:
    """Gera o link "Conectar Google Drive" para o escritório fazer login."""
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Composio não configurado — defina COMPOSIO_API_KEY e o auth config",
        )
    link = await client.criar_link(USER_ID_PADRAO)
    return {"redirect_url": link.redirect_url}
