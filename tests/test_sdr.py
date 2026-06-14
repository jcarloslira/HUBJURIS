"""Testes do agente SDR e serviço de qualificação."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.sdr import SYSTEM_PROMPT, SDRAgent
from app.services.sdr import SDRService


def _mock_anthropic(texto: str) -> AsyncMock:
    """Cria mock do Anthropic que retorna texto fixo."""
    bloco = MagicMock()
    bloco.type = "text"
    bloco.text = texto
    response = MagicMock()
    response.content = [bloco]
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


def _chainable_table(data: list) -> MagicMock:
    """Cria mock de tabela Supabase com chain síncrona e execute async."""
    table = MagicMock()
    table.select.return_value = table
    table.insert.return_value = table
    table.update.return_value = table
    table.eq.return_value = table
    table.lte.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.execute = AsyncMock(return_value=MagicMock(data=data))
    return table


class TestSDRAgent:
    """Testes do agente SDR."""

    def test_system_prompt_contem_superendividamento(self) -> None:
        assert "superendividamento" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contem_dr_vinicius(self) -> None:
        assert "Dr. Vinícius" in SYSTEM_PROMPT

    def test_system_prompt_contem_lei(self) -> None:
        assert "14.181/2021" in SYSTEM_PROMPT

    def test_system_prompt_contem_lorena(self) -> None:
        assert "Lorena" in SYSTEM_PROMPT

    def test_system_prompt_contem_gestao_passivo(self) -> None:
        assert "Gestão de Passivo" in SYSTEM_PROMPT

    def test_system_prompt_contem_cnpj(self) -> None:
        assert "CNPJ" in SYSTEM_PROMPT

    def test_max_tokens_curto(self) -> None:
        agent = SDRAgent(AsyncMock())
        assert agent.max_tokens == 512

    @pytest.mark.asyncio
    async def test_processar_retorna_resposta(self) -> None:
        client = _mock_anthropic("Oi! Aqui é a Lorena, do Lassi Leocádio!")
        agent = SDRAgent(client)

        resposta = await agent.processar("Oi, preciso de ajuda com dívidas")

        assert "Lorena" in resposta
        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["max_tokens"] == 512
        assert "superendividamento" in kwargs["system"].lower()


class TestSDRService:
    """Testes do serviço SDR."""

    @pytest.mark.asyncio
    async def test_registrar_lead_novo(self) -> None:
        lead_data = {
            "id": "uuid-123",
            "telefone": "5511999999999",
            "nome": "João",
            "tipo": None,
            "etapa_funil": "novo",
            "valor_divida": None,
            "qtd_credores": None,
            "renda_mensal": None,
            "tipos_divida": None,
            "observacoes": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

        select_table = _chainable_table([])
        insert_table = _chainable_table([lead_data])

        call_count = 0

        def _table(name: str) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return select_table
            return insert_table

        db = MagicMock()
        db.table = MagicMock(side_effect=_table)

        svc = SDRService(db, AsyncMock())
        lead = await svc.registrar_lead("5511999999999", "João")

        assert lead.telefone == "5511999999999"
        assert lead.nome == "João"

    @pytest.mark.asyncio
    async def test_registrar_lead_existente(self) -> None:
        lead_data = {
            "id": "uuid-123",
            "telefone": "5511999999999",
            "nome": "Maria",
            "tipo": "cpf",
            "etapa_funil": "em_qualificacao",
            "valor_divida": 50000.0,
            "qtd_credores": 3,
            "renda_mensal": 5000.0,
            "tipos_divida": ["cartao", "emprestimo"],
            "observacoes": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

        table = _chainable_table([lead_data])
        db = MagicMock()
        db.table = MagicMock(return_value=table)

        svc = SDRService(db, AsyncMock())
        lead = await svc.registrar_lead("5511999999999")

        assert lead.nome == "Maria"
        assert lead.etapa_funil == "em_qualificacao"

    @pytest.mark.asyncio
    async def test_obter_historico_formata_mensagens(self) -> None:
        msgs = [
            {"direcao": "entrada", "conteudo": "Oi"},
            {"direcao": "saida", "conteudo": "Olá!"},
            {"direcao": "entrada", "conteudo": "Preciso de ajuda"},
        ]

        table = _chainable_table(msgs)
        db = MagicMock()
        db.table = MagicMock(return_value=table)

        svc = SDRService(db, AsyncMock())
        historico = await svc.obter_historico("uuid-123")

        assert len(historico) == 3
        assert historico[0]["role"] == "user"
        assert historico[1]["role"] == "assistant"
        assert historico[2]["role"] == "user"

    @pytest.mark.asyncio
    async def test_obter_metricas(self) -> None:
        rows = [
            {"etapa_funil": "novo"},
            {"etapa_funil": "novo"},
            {"etapa_funil": "em_qualificacao"},
            {"etapa_funil": "agendado"},
        ]

        table = _chainable_table(rows)
        db = MagicMock()
        db.table = MagicMock(return_value=table)

        svc = SDRService(db, AsyncMock())
        metricas = await svc.obter_metricas()

        assert metricas.novo == 2
        assert metricas.em_qualificacao == 1
        assert metricas.agendado == 1
        assert metricas.total == 4
