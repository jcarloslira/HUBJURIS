"""Testes da classe base dos agentes."""

from unittest.mock import AsyncMock, MagicMock

from app.agents.base import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, BaseAgent


def _mock_anthropic(texto: str) -> AsyncMock:
    bloco = MagicMock()
    bloco.type = "text"
    bloco.text = texto
    response = MagicMock()
    response.content = [bloco]
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


async def test_processar_retorna_texto_da_resposta() -> None:
    client = _mock_anthropic("Olá!")
    agente = BaseAgent(client)

    resultado = await agente.processar("Oi")

    assert resultado == "Olá!"


async def test_processar_inclui_historico_e_parametros() -> None:
    client = _mock_anthropic("ok")
    agente = BaseAgent(client)
    historico = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "sim"}]

    await agente.processar("agora", historico=historico)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == DEFAULT_MODEL
    assert kwargs["max_tokens"] == DEFAULT_MAX_TOKENS
    assert kwargs["messages"] == historico + [{"role": "user", "content": "agora"}]
    # O histórico original não pode ser mutado pelo agente
    assert len(historico) == 2
