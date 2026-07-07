"""Router para receber webhooks da W-API (WhatsApp)."""

import logging

from fastapi import APIRouter, BackgroundTasks, Request, status

from app.schemas.webhook import WAPIWebhookPayload
from app.services.sdr import SDRService
from app.services.whatsapp import WhatsAppClient

router = APIRouter(prefix="/api/webhook", tags=["webhook"])

logger = logging.getLogger(__name__)


async def _processar_e_responder(
    sdr_service: SDRService,
    whatsapp: WhatsAppClient,
    telefone: str,
    texto: str,
    push_name: str | None,
) -> None:
    """Processa a mensagem com o agente e envia a resposta via WhatsApp.

    Args:
        sdr_service: Serviço SDR para orquestração.
        whatsapp: Cliente W-API para envio.
        telefone: Número do lead.
        texto: Mensagem recebida.
        push_name: Nome do contato.
    """
    try:
        resposta = await sdr_service.processar_mensagem(telefone, texto, push_name)
        await whatsapp.enviar_texto(telefone, resposta)
    except Exception:
        logger.exception("Erro ao processar mensagem de %s", telefone)


@router.post("/wapi", status_code=status.HTTP_200_OK)
async def receber_webhook_wapi(
    payload: WAPIWebhookPayload,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Recebe mensagens da W-API e processa em background.

    Retorna 200 imediatamente para não bloquear o webhook.
    """
    raw = payload.model_dump(exclude_none=True)
    print(f"[WEBHOOK RAW] {raw}")
    dados = payload.resolver_dados()
    texto_debug = dados.extrair_texto()
    tel_debug = dados.extrair_telefone()
    print(
        f"[WEBHOOK] texto={texto_debug} telefone={tel_debug}"
        f" fromMe={dados.eh_mensagem_propria()} grupo={dados.eh_grupo()}"
    )

    if dados.eh_mensagem_propria():
        return {"status": "ignored", "reason": "from_me"}

    texto = dados.extrair_texto()
    if not texto:
        return {"status": "ignored", "reason": "no_text"}

    if dados.eh_grupo():
        return {"status": "ignored", "reason": "group_message"}

    telefone = dados.extrair_telefone()
    if not telefone:
        return {"status": "ignored", "reason": "no_phone"}

    push_name = dados.extrair_nome()

    supabase = request.app.state.supabase
    anthropic = request.app.state.anthropic
    http_client = request.app.state.http_client

    if supabase is None:
        return {"status": "error", "reason": "supabase_not_configured"}

    from app.config import get_settings

    sdr_service = SDRService(supabase, anthropic)
    whatsapp = WhatsAppClient(http_client, get_settings())

    background_tasks.add_task(
        _processar_e_responder,
        sdr_service,
        whatsapp,
        telefone,
        texto,
        push_name,
    )

    return {"status": "processing"}
