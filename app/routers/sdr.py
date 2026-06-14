"""Router administrativo do SDR: leads, agendamentos, métricas."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user
from app.schemas.auth import AuthUser
from app.schemas.sdr import (
    AgendamentoCreate,
    AgendamentoResponse,
    EtapaFunil,
    LeadDetalhe,
    LeadResponse,
    LeadUpdate,
    MetricasFunil,
)
from app.services.sdr import SDRService

router = APIRouter(prefix="/api/sdr", tags=["sdr"])


def _get_sdr_service(request: Request) -> SDRService:
    """Cria uma instância do SDRService com os clientes da aplicação."""
    return SDRService(request.app.state.supabase, request.app.state.anthropic)


Auth = Annotated[AuthUser, Depends(get_current_user)]
Svc = Annotated[SDRService, Depends(_get_sdr_service)]


# ── Leads ──────────────────────────────────────────────────────────


@router.get(
    "/leads",
    response_model=list[LeadResponse],
    status_code=status.HTTP_200_OK,
)
async def listar_leads(
    _user: Auth,
    svc: Svc,
    etapa: EtapaFunil | None = None,
    limite: int = 50,
) -> list[LeadResponse]:
    """Lista leads com filtro opcional por etapa do funil."""
    return await svc.listar_leads(etapa=etapa, limite=limite)


@router.get(
    "/leads/{lead_id}",
    response_model=LeadDetalhe,
    status_code=status.HTTP_200_OK,
)
async def obter_lead(lead_id: str, _user: Auth, svc: Svc) -> LeadDetalhe:
    """Retorna detalhes do lead com histórico de mensagens e agendamentos."""
    detalhe = await svc.obter_lead_detalhe(lead_id)
    if detalhe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado",
        )
    return detalhe


@router.patch(
    "/leads/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
)
async def atualizar_lead(lead_id: str, dados: LeadUpdate, _user: Auth, svc: Svc) -> LeadResponse:
    """Atualiza dados de qualificação de um lead."""
    lead = await svc.atualizar_lead(lead_id, dados)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado ou nenhum dado para atualizar",
        )
    return lead


# ── Agendamentos ───────────────────────────────────────────────────


@router.get(
    "/agendamentos",
    response_model=list[AgendamentoResponse],
    status_code=status.HTTP_200_OK,
)
async def listar_agendamentos(_user: Auth, svc: Svc, limite: int = 50) -> list[AgendamentoResponse]:
    """Lista todos os agendamentos de consulta."""
    return await svc.listar_agendamentos(limite=limite)


@router.post(
    "/agendamentos",
    response_model=AgendamentoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def criar_agendamento(dados: AgendamentoCreate, _user: Auth, svc: Svc) -> AgendamentoResponse:
    """Cria um agendamento de consulta manualmente."""
    return await svc.agendar_consulta(dados)


# ── Métricas ───────────────────────────────────────────────────────


@router.get(
    "/metricas",
    response_model=MetricasFunil,
    status_code=status.HTTP_200_OK,
)
async def obter_metricas(_user: Auth, svc: Svc) -> MetricasFunil:
    """Retorna contagem de leads por etapa do funil."""
    return await svc.obter_metricas()


# ── Follow-ups manuais ────────────────────────────────────────────


@router.post(
    "/followup/{lead_id}",
    status_code=status.HTTP_200_OK,
)
async def disparar_followup(
    lead_id: str, request: Request, _user: Auth, svc: Svc
) -> dict[str, str]:
    """Envia um follow-up manual para o lead via WhatsApp."""
    detalhe = await svc.obter_lead_detalhe(lead_id)
    if detalhe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado",
        )

    from app.config import get_settings
    from app.services.whatsapp import WhatsAppClient

    http_client = request.app.state.http_client
    whatsapp = WhatsAppClient(http_client, get_settings())

    resposta = await svc.processar_mensagem(
        detalhe.lead.telefone,
        "[FOLLOW-UP] O lead não respondeu. Envie uma mensagem de acompanhamento.",
        detalhe.lead.nome,
    )

    enviado = await whatsapp.enviar_texto(detalhe.lead.telefone, resposta)

    if not enviado:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao enviar mensagem via WhatsApp",
        )

    return {"status": "sent", "lead_id": lead_id}
