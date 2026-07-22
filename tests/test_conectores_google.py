"""Testes dos conectores Google: fábrica de clientes + ferramentas de ação."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from app.agents.ferramentas_google import (
    FERRAMENTAS_GOOGLE,
    ferramentas_google_disponiveis,
    montar_handlers_google,
)
from app.config import Settings
from app.services.composio_drive import ComposioError
from app.services.conectores import auth_config_de, client_para, nome_de


def _settings(**extra: str) -> Settings:
    # _env_file=None ignora o .env real (que já tem os IDs do Composio).
    return Settings(_env_file=None, COMPOSIO_API_KEY="ak_x", **extra)  # type: ignore[call-arg]


# ── Fábrica de clientes ─────────────────────────────────────────


def test_client_para_none_sem_api_key() -> None:
    s = Settings(_env_file=None, COMPOSIO_GCALENDAR_AUTH_CONFIG_ID="ac_1")  # type: ignore[call-arg]
    assert client_para(s, httpx.AsyncClient(), "agenda") is None


def test_client_para_none_sem_auth_config() -> None:
    assert client_para(_settings(), httpx.AsyncClient(), "agenda") is None


def test_client_para_ok() -> None:
    s = _settings(COMPOSIO_GCALENDAR_AUTH_CONFIG_ID="ac_cal")
    cli = client_para(s, httpx.AsyncClient(), "agenda")
    assert cli is not None
    assert auth_config_de(s, "agenda") == "ac_cal"
    assert nome_de("agenda") == "Google Agenda"


# ── Disponibilidade das ferramentas ─────────────────────────────


def test_ferramentas_disponiveis_filtra_por_conector() -> None:
    clients = {"agenda": MagicMock(), "gmail": None, "docs": None, "sheets": None}
    nomes = {f["name"] for f in ferramentas_google_disponiveis(clients)}
    assert nomes == {"criar_evento_agenda"}
    # todas existem no catálogo completo
    assert len(FERRAMENTAS_GOOGLE) == 4


# ── Handlers de ação ────────────────────────────────────────────


async def test_criar_evento_monta_args_corretos() -> None:
    agenda = MagicMock()
    agenda.executar_acao = AsyncMock(return_value={})
    handlers = montar_handlers_google({"agenda": agenda}, "esc1")

    saida = await handlers["criar_evento_agenda"](
        {
            "titulo": "Assembleia",
            "inicio": "2026-08-05T19:00:00",
            "duracao_minutos": 90,
            "criar_link_meet": True,
        }
    )

    assert "Assembleia" in saida and "Meet" in saida
    tool, user_id, args = agenda.executar_acao.await_args.args
    assert tool == "GOOGLECALENDAR_CREATE_EVENT"
    assert user_id == "esc1"
    assert args["summary"] == "Assembleia"
    assert args["event_duration_hour"] == 1 and args["event_duration_minutes"] == 30
    assert args["create_meeting_room"] is True
    assert args["timezone"] == "America/Sao_Paulo"


async def test_acao_sem_conector_avisa() -> None:
    handlers = montar_handlers_google({"gmail": None}, "esc1")
    saida = await handlers["rascunhar_email"]({"para": "x@y.com", "assunto": "Oi", "corpo": "..."})
    assert "não está disponível" in saida.lower()


async def test_acao_sem_conexao_orienta_conectar() -> None:
    docs = MagicMock()
    docs.executar_acao = AsyncMock(side_effect=ComposioError("No connected account found"))
    handlers = montar_handlers_google({"docs": docs}, "esc1")

    saida = await handlers["criar_documento_google"](
        {"titulo": "Petição", "conteudo_markdown": "# x"}
    )

    assert "conectar" in saida.lower()


async def test_rascunhar_email_usa_draft() -> None:
    gmail = MagicMock()
    gmail.executar_acao = AsyncMock(return_value={})
    handlers = montar_handlers_google({"gmail": gmail}, "esc1")

    saida = await handlers["rascunhar_email"](
        {"para": "sindico@cond.com", "assunto": "Cobrança", "corpo": "Prezado..."}
    )

    tool = gmail.executar_acao.await_args.args[0]
    assert tool == "GMAIL_CREATE_EMAIL_DRAFT"
    assert "rascunho" in saida.lower()
