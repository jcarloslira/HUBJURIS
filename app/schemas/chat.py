"""Schemas do recurso de chat com agentes."""

from typing import Literal

from pydantic import BaseModel, Field

ModeloPermitido = Literal[
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-8",
]


class MensagemChat(BaseModel):
    """Uma mensagem do histórico da conversa."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Payload de envio de mensagem para um agente."""

    agente: str = Field(min_length=1)
    mensagens: list[MensagemChat] = Field(min_length=1)
    modelo: ModeloPermitido | None = None


class AgenteInfo(BaseModel):
    """Metadados públicos de um agente disponível no hub."""

    slug: str
    nome: str
    descricao: str
    icone: str
