"""Router do chat com os agentes do hub."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.dependencies_google import USER_ID_PADRAO, get_composio_client
from app.schemas.chat import AgenteInfo, ChatRequest
from app.services import chat as chat_service
from app.services.composio_drive import ComposioClient, ComposioDriveConnector

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/agentes", response_model=list[AgenteInfo], status_code=200)
async def listar_agentes() -> list[AgenteInfo]:
    """Lista os agentes especialistas disponíveis no hub."""
    return chat_service.listar_agentes()


@router.post("/chat", status_code=200)
async def conversar(
    payload: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    composio: Annotated[ComposioClient | None, Depends(get_composio_client)],
) -> StreamingResponse:
    """Envia o histórico ao agente escolhido (ou roteia via Supervisor) em streaming.

    Se o Composio estiver configurado e a pasta do acervo definida, o
    especialista é aterrado nos modelos do escritório.
    """
    if not chat_service.agente_existe(payload.agente):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente desconhecido: {payload.agente}",
        )

    acervo_raiz = settings.COMPOSIO_ACERVO_FOLDER_ID or None
    conector = (
        ComposioDriveConnector(composio, USER_ID_PADRAO)
        if composio is not None and acervo_raiz
        else None
    )

    return StreamingResponse(
        chat_service.gerar_resposta_stream(
            payload,
            request.app.state.anthropic,
            conector=conector,
            acervo_raiz=acervo_raiz,
        ),
        media_type="text/plain; charset=utf-8",
    )
