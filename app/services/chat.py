"""Lógica de negócio do chat: registro de agentes e geração de respostas."""

from collections.abc import AsyncIterator
from typing import cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from app.agents.base import BaseAgent
from app.agents.contratos import ContratosAgent
from app.agents.juridico_geral import JuridicoGeralAgent
from app.agents.peticoes import PeticoesAgent
from app.agents.processos import ProcessosAgent
from app.schemas.chat import AgenteInfo, ChatRequest

_REGISTRO: dict[str, tuple[type[BaseAgent], AgenteInfo]] = {
    "juridico-geral": (
        JuridicoGeralAgent,
        AgenteInfo(
            slug="juridico-geral",
            nome="Jurídico Geral",
            descricao="Dúvidas de direito brasileiro com fundamentação legal",
            icone="scale",
        ),
    ),
    "peticoes": (
        PeticoesAgent,
        AgenteInfo(
            slug="peticoes",
            nome="Petições",
            descricao="Redação de peças processuais com técnica forense",
            icone="file-text",
        ),
    ),
    "processos": (
        ProcessosAgent,
        AgenteInfo(
            slug="processos",
            nome="Processos",
            descricao="Andamentos, prazos e gestão da carteira processual",
            icone="gavel",
        ),
    ),
    "contratos": (
        ContratosAgent,
        AgenteInfo(
            slug="contratos",
            nome="Contratos",
            descricao="Minutas, revisão e análise de risco de contratos",
            icone="signature",
        ),
    ),
}


def listar_agentes() -> list[AgenteInfo]:
    """Retorna os metadados de todos os agentes disponíveis no hub."""
    return [info for _, info in _REGISTRO.values()]


def obter_agente(slug: str, client: AsyncAnthropic) -> BaseAgent | None:
    """Instancia o agente correspondente ao slug, ou None se não existir.

    Args:
        slug: Identificador do agente (ex: "peticoes").
        client: Cliente Anthropic compartilhado da aplicação.

    Returns:
        Instância do agente ou None quando o slug é desconhecido.
    """
    entrada = _REGISTRO.get(slug)
    if entrada is None:
        return None
    classe, _ = entrada
    return classe(client)


async def gerar_resposta_stream(agente: BaseAgent, payload: ChatRequest) -> AsyncIterator[str]:
    """Gera a resposta do agente em streaming a partir do payload do chat.

    Args:
        agente: Agente já instanciado.
        payload: Requisição validada com histórico e modelo.

    Yields:
        Trechos de texto da resposta.
    """
    mensagens = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.content} for m in payload.mensagens],
    )
    async for trecho in agente.responder_stream(mensagens, modelo=payload.modelo):
        yield trecho
