"""Router do chat com os agentes do hub."""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.schemas.chat import AgenteInfo, ChatRequest
from app.services import chat as chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/agentes", response_model=list[AgenteInfo], status_code=200)
async def listar_agentes() -> list[AgenteInfo]:
    """Lista os agentes especialistas disponíveis no hub."""
    return chat_service.listar_agentes()


@router.post("/chat", status_code=200)
async def conversar(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Envia o histórico ao agente escolhido (ou roteia via Supervisor) em streaming."""
    if not chat_service.agente_existe(payload.agente):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente desconhecido: {payload.agente}",
        )
    return StreamingResponse(
        chat_service.gerar_resposta_stream(payload, request.app.state.anthropic),
        media_type="text/plain; charset=utf-8",
    )
