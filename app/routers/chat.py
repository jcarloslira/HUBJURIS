"""Router do chat com os agentes do hub."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.dependencies_google import USER_ID_PADRAO, get_composio_client
from app.schemas.chat import AgenteInfo, ChatRequest
from app.services import chat as chat_service
from app.services.composio_drive import ComposioClient, ComposioDriveConnector
from app.services.contas import ContaService

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/agentes", response_model=list[AgenteInfo], status_code=200)
async def listar_agentes() -> list[AgenteInfo]:
    """Lista os agentes especialistas disponíveis no hub."""
    return chat_service.listar_agentes()


async def _montar_registro_uso(request: Request, authorization: str | None):
    """Se houver token válido, devolve callback que grava o uso do escritório.

    Token ausente/ inválido não bloqueia o chat (o app local segue útil);
    apenas deixa de medir o consumo por conta.
    """
    supabase = request.app.state.supabase
    if supabase is None or not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        resp = await supabase.auth.get_user(token)
        if resp is None or resp.user is None:
            return None
        svc = ContaService(supabase, request.app.state.http_client, get_settings())
        perfil = await svc.perfil(str(resp.user.id))
    except Exception:  # noqa: BLE001 - medição é opcional
        return None

    async def registrar(agente: str, modelo: str, tokens_in: int, tokens_out: int) -> None:
        try:
            await svc.registrar_uso(
                escritorio_id=perfil.escritorio_id,
                user_id=perfil.user_id,
                agente=agente,
                modelo=modelo,
                tokens_entrada=tokens_in,
                tokens_saida=tokens_out,
            )
        except Exception:  # noqa: BLE001
            pass

    return registrar


@router.post("/chat", status_code=200)
async def conversar(
    payload: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    composio: Annotated[ComposioClient | None, Depends(get_composio_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Envia o histórico ao agente escolhido (ou roteia via Supervisor) em streaming.

    Com Composio configurado + pasta do acervo, o especialista é aterrado nos
    modelos do escritório. Com token de sessão, o consumo real de tokens é
    gravado para o painel de Uso.
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
    on_usage = await _montar_registro_uso(request, authorization)

    return StreamingResponse(
        chat_service.gerar_resposta_stream(
            payload,
            request.app.state.anthropic,
            conector=conector,
            acervo_raiz=acervo_raiz,
            on_usage=on_usage,
        ),
        media_type="text/plain; charset=utf-8",
    )
