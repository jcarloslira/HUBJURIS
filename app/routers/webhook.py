"""Router para receber webhooks da Evolution API (WhatsApp)."""

import logging

from fastapi import APIRouter, BackgroundTasks, Request, status

from app.schemas.webhook import EvolutionWebhookPayload
from app.services.evolution import EvolutionClient
from app.services.sdr import SDRService

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

logger = logging.getLogger(__name__)


async def _processar_e_responder(
    sdr_service: SDRService,
    evolution: EvolutionClient,
    telefone: str,
    texto: str,
    push_name: str | None,
) -> None:
    """Processa a mensagem com o agente e envia a resposta via WhatsApp.

    Args:
        sdr_service: Serviço SDR para orquestração.
        evolution: Cliente Evolution API para envio.
        telefone: Número do lead.
        texto: Mensagem recebida.
        push_name: Nome do contato.
    """
    try:
        resposta = await sdr_service.processar_mensagem(telefone, texto, push_name)
        await evolution.enviar_texto(telefone, resposta)
    except Exception:
        logger.exception("Erro ao processar mensagem de %s", telefone)


@router.post("/evolution", status_code=status.HTTP_200_OK)
async def receber_webhook_evolution(
    payload: EvolutionWebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Recebe mensagens da Evolution API e processa em background.

    Retorna 200 imediatamente para não bloquear o webhook.
    """
    if payload.event and payload.event != "messages.upsert":
        return {"status": "ignored", "reason": "event_type"}

    if payload.data.key.fromMe:
        return {"status": "ignored", "reason": "from_me"}

    texto = payload.data.extrair_texto()
    if not texto:
        return {"status": "ignored", "reason": "no_text"}

    if payload.data.key.remoteJid.endswith("@g.us"):
        return {"status": "ignored", "reason": "group_message"}

    telefone = payload.data.extrair_telefone()
    push_name = payload.data.pushName

    supabase = request.app.state.supabase
    anthropic = request.app.state.anthropic
    http_client = request.app.state.http_client

    if supabase is None:
        return {"status": "error", "reason": "supabase_not_configured"}

    from app.config import get_settings

    sdr_service = SDRService(supabase, anthropic)
    evolution = EvolutionClient(http_client, get_settings())

    background_tasks.add_task(
        _processar_e_responder,
        sdr_service,
        evolution,
        telefone,
        texto,
        push_name,
    )

    return {"status": "processing"}
