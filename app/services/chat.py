"""Lógica de negócio do chat: registro de agentes, roteamento e streaming."""

from collections.abc import AsyncIterator
from typing import cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from app.agents.base import BaseAgent
from app.agents.consulta_historica import ConsultaHistoricaAgent
from app.agents.contratos import ContratosAgent
from app.agents.juridico_geral import JuridicoGeralAgent
from app.agents.notificacoes import NotificacoesAgent
from app.agents.pareceres import PareceresAgent
from app.agents.peticoes import PeticoesAgent
from app.agents.supervisor import SupervisorAgent
from app.schemas.chat import AgenteInfo, ChatRequest

_REGISTRO: dict[str, tuple[type[BaseAgent], AgenteInfo]] = {
    "supervisor": (
        SupervisorAgent,
        AgenteInfo(
            slug="supervisor",
            nome="Supervisor",
            descricao="Primeiro contato, onboarding do escritório e encaminhamento",
            icone="compass",
        ),
    ),
    "notificacoes": (
        NotificacoesAgent,
        AgenteInfo(
            slug="notificacoes",
            nome="Notificações",
            descricao="Notificações a condôminos a partir de um comando simples",
            icone="bell",
        ),
    ),
    "peticoes": (
        PeticoesAgent,
        AgenteInfo(
            slug="peticoes",
            nome="Petições",
            descricao="Peças do contencioso condominial (cobrança de cotas, execução)",
            icone="file-text",
        ),
    ),
    "contratos": (
        ContratosAgent,
        AgenteInfo(
            slug="contratos",
            nome="Contratos",
            descricao="Minutas, análise de risco, vencimento e rescisão",
            icone="signature",
        ),
    ),
    "pareceres": (
        PareceresAgent,
        AgenteInfo(
            slug="pareceres",
            nome="Pareceres",
            descricao="Pareceres jurídicos condominiais fundamentados",
            icone="scroll",
        ),
    ),
    "consulta-historica": (
        ConsultaHistoricaAgent,
        AgenteInfo(
            slug="consulta-historica",
            nome="Consulta Histórica",
            descricao="Síndico atual, reajustes, deliberações e atas do acervo",
            icone="history",
        ),
    ),
    "juridico-geral": (
        JuridicoGeralAgent,
        AgenteInfo(
            slug="juridico-geral",
            nome="Jurídico Geral",
            descricao="Dúvidas de direito condominial com fundamentação",
            icone="scale",
        ),
    ),
}

MODELO_ROTEAMENTO = "claude-haiku-4-5-20251001"

_ROTEAVEIS = [s for s in _REGISTRO if s != "supervisor"]

_ROTEAR_TOOL = {
    "name": "rotear",
    "description": (
        "Encaminha a demanda do usuário ao especialista adequado, ou mantém com o "
        "Supervisor para onboarding e conversa geral."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "especialista": {
                "type": "string",
                "enum": [*_ROTEAVEIS, "supervisor"],
                "description": (
                    "slug do especialista: 'notificacoes', 'peticoes', 'contratos', "
                    "'pareceres', 'consulta-historica', 'juridico-geral'; ou 'supervisor' "
                    "para saudação, onboarding ou dúvida sobre a plataforma."
                ),
            }
        },
        "required": ["especialista"],
    },
}

ROTEAMENTO_PROMPT = """Você roteia a mensagem de um hub jurídico condominial para o especialista \
adequado. Analise o histórico e a última mensagem e escolha UM destino chamando a ferramenta \
'rotear'. Use 'notificacoes' para pedidos de notificação a condômino/unidade; 'peticoes' para \
peças processuais (cobrança de cotas, execução, ações); 'contratos' para elaboração/revisão de \
contrato, vencimento ou rescisão; 'pareceres' para pareceres fundamentados; 'consulta-historica' \
para perguntas factuais do acervo (síndico atual, reajuste, deliberações, atas); 'juridico-geral' \
para dúvidas jurídicas gerais de direito condominial; 'supervisor' para saudações, onboarding, \
dúvidas sobre a plataforma ou quando não estiver claro."""


def listar_agentes() -> list[AgenteInfo]:
    """Retorna os metadados de todos os agentes disponíveis no hub."""
    return [info for _, info in _REGISTRO.values()]


def agente_existe(slug: str) -> bool:
    """Indica se o slug corresponde a um agente registrado."""
    return slug in _REGISTRO


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


async def escolher_especialista(client: AsyncAnthropic, mensagens: list[MessageParam]) -> str:
    """Decide, via tool use, para qual agente encaminhar a conversa.

    Args:
        client: Cliente Anthropic compartilhado.
        mensagens: Histórico completo da conversa.

    Returns:
        Slug do agente escolhido; "supervisor" como padrão seguro.
    """
    resposta = await client.messages.create(
        model=MODELO_ROTEAMENTO,
        max_tokens=512,
        system=ROTEAMENTO_PROMPT,
        messages=mensagens,
        tools=[_ROTEAR_TOOL],
        tool_choice={"type": "tool", "name": "rotear"},
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use" and bloco.name == "rotear":
            slug = bloco.input.get("especialista", "supervisor")
            return slug if slug in _REGISTRO else "supervisor"
    return "supervisor"


async def gerar_resposta_stream(payload: ChatRequest, client: AsyncAnthropic) -> AsyncIterator[str]:
    """Gera a resposta em streaming, roteando quando o alvo é o Supervisor.

    Args:
        payload: Requisição validada com agente, histórico e modelo.
        client: Cliente Anthropic compartilhado.

    Yields:
        Trechos de texto da resposta do agente que efetivamente atende.
    """
    mensagens = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.content} for m in payload.mensagens],
    )
    slug = payload.agente
    if slug == "supervisor":
        slug = await escolher_especialista(client, mensagens)
    agente = obter_agente(slug, client) or obter_agente("supervisor", client)
    assert agente is not None  # supervisor está sempre registrado
    async for trecho in agente.responder_stream(mensagens, modelo=payload.modelo):
        yield trecho
