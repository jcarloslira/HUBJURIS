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


@pytest.mark.asyncio
async def test_handler_leitura_chama_rota_certa() -> None:
    client = AsyncMock()
    client.chamar.return_value = {"data": [{"numero": "123", "nome_cliente": "COND. LARA"}]}
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["easyjur_processos"]({})

    client.chamar.assert_awaited_once_with("/api/easyjur/list/processos", {})
    assert "COND. LARA" in saida


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
