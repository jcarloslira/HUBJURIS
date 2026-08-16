"""Testes do conector mcp.ai (EasyJur/Tiflux): cliente e ferramentas dos agentes."""

from unittest.mock import AsyncMock

import pytest

from app.agents.ferramentas_mcpai import (
    FERRAMENTAS_MCPAI,
    NOMES_MCPAI,
    montar_handlers_mcpai,
)
from app.services.mcpai import MCPAIClient, MCPAIError


class _Settings:
    MCP_AI_API_KEY = "sk_live_x"
    MCP_AI_BASE_URL = "https://api.mcp.ai"


class _SettingsVazio(_Settings):
    MCP_AI_API_KEY = ""


def test_ativo_depende_da_key() -> None:
    assert MCPAIClient(AsyncMock(), _Settings()).ativo is True
    assert MCPAIClient(AsyncMock(), _SettingsVazio()).ativo is False


def test_schemas_e_nomes_batem() -> None:
    nomes = {f["name"] for f in FERRAMENTAS_MCPAI}
    assert nomes == NOMES_MCPAI
    assert "easyjur_processos" in nomes and "tiflux_criar_ticket" in nomes


def test_paginacao_de_processos_usa_page() -> None:
    """A API do EasyJur ignora em silêncio qualquer outro nome (ex.: 'pagina') e
    devolve sempre a página 1 — o agente conclui que não há mais nada e erra o total."""
    processos = next(f for f in FERRAMENTAS_MCPAI if f["name"] == "easyjur_processos")
    props = processos["input_schema"]["properties"]
    assert "page" in props, "o parâmetro de paginação precisa se chamar 'page'"
    assert "pagina" not in props


@pytest.mark.asyncio
async def test_handler_leitura_chama_rota_certa() -> None:
    client = AsyncMock()
    client.chamar.return_value = {
        "data": [{"numero": "123", "nome_contrario": "FULANO", "campo_ruido": "x" * 500}],
        "meta": {"total": 42, "total_pages": 3},
        "raw_data": "x" * 9000,  # a API duplica tudo aqui — deve ser removido
    }
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["easyjur_processos"]({})

    client.chamar.assert_awaited_once_with("/api/easyjur/list/processos", {})
    assert "123" in saida and "FULANO" in saida  # campos essenciais mantidos
    assert "campo_ruido" not in saida  # ruído do processo é enxugado
    assert "raw_data" not in saida  # duplicata gigante removida
    assert '"total": 42' in saida and '"total_pages": 3' in saida  # meta preservado p/ paginar


@pytest.mark.asyncio
async def test_handler_escrita_repassa_args() -> None:
    client = AsyncMock()
    client.chamar.return_value = {"ticket_number": 999}
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["tiflux_criar_ticket"](
        {"title": "Vazamento", "description": "Apto 42"}
    )

    path, args = client.chamar.call_args.args
    assert path == "/api/tiflux/create/ticket"
    assert args["title"] == "Vazamento"
    assert "999" in saida


@pytest.mark.asyncio
async def test_handler_erro_vira_mensagem_amigavel() -> None:
    client = AsyncMock()
    client.chamar.side_effect = MCPAIError("boom")
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["tiflux_tickets"]({})

    assert "Tiflux" in saida and "boom" in saida
