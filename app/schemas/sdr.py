"""Schemas Pydantic para o módulo SDR (leads, mensagens, agendamentos)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EtapaFunil = Literal[
    "novo",
    "em_qualificacao",
    "qualificado",
    "agendado",
    "convertido",
    "descartado",
]

TipoLead = Literal["cpf", "cnpj"]
DirecaoMensagem = Literal["entrada", "saida"]
TipoAgendamento = Literal["presencial", "online"]
StatusAgendamento = Literal["confirmado", "cancelado", "realizado"]
TipoFollowUp = Literal["lembrete", "follow_up"]


# ── Leads ──────────────────────────────────────────────────────────


class LeadCreate(BaseModel):
    """Dados para registrar um novo lead."""

    telefone: str = Field(min_length=10, max_length=20)
    nome: str | None = None
    tipo: TipoLead | None = None


class LeadUpdate(BaseModel):
    """Dados atualizáveis de um lead."""

    nome: str | None = None
    tipo: TipoLead | None = None
    etapa_funil: EtapaFunil | None = None
    valor_divida: float | None = None
    qtd_credores: int | None = None
    renda_mensal: float | None = None
    tipos_divida: list[str] | None = None
    observacoes: str | None = None


class LeadResponse(BaseModel):
    """Lead completo retornado pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    telefone: str
    nome: str | None = None
    tipo: TipoLead | None = None
    etapa_funil: EtapaFunil = "novo"
    valor_divida: float | None = None
    qtd_credores: int | None = None
    renda_mensal: float | None = None
    tipos_divida: list[str] | None = None
    observacoes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Mensagens SDR ──────────────────────────────────────────────────


class MensagemSDRResponse(BaseModel):
    """Mensagem de conversa com lead."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    lead_id: str
    direcao: DirecaoMensagem
    conteudo: str
    created_at: datetime


# ── Agendamentos ───────────────────────────────────────────────────


class AgendamentoCreate(BaseModel):
    """Dados para criar um agendamento de consulta."""

    lead_id: str
    data_hora: datetime
    tipo: TipoAgendamento = "online"
    observacoes: str | None = None


class AgendamentoResponse(BaseModel):
    """Agendamento retornado pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    lead_id: str
    data_hora: datetime
    tipo: TipoAgendamento
    status: StatusAgendamento = "confirmado"
    observacoes: str | None = None
    created_at: datetime


# ── Follow-ups ─────────────────────────────────────────────────────


class FollowUpCreate(BaseModel):
    """Dados para agendar um follow-up."""

    lead_id: str
    tipo: TipoFollowUp = "follow_up"
    mensagem: str
    data_agendada: datetime


class FollowUpResponse(BaseModel):
    """Follow-up retornado pela API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    lead_id: str
    tipo: TipoFollowUp
    mensagem: str
    data_agendada: datetime
    enviado: bool = False
    created_at: datetime


# ── Métricas ───────────────────────────────────────────────────────


class MetricasFunil(BaseModel):
    """Contagem de leads por etapa do funil."""

    novo: int = 0
    em_qualificacao: int = 0
    qualificado: int = 0
    agendado: int = 0
    convertido: int = 0
    descartado: int = 0
    total: int = 0


# ── Lead com histórico (detalhe) ───────────────────────────────────


class LeadDetalhe(BaseModel):
    """Lead com histórico de mensagens e agendamentos."""

    lead: LeadResponse
    mensagens: list[MensagemSDRResponse] = []
    agendamentos: list[AgendamentoResponse] = []
