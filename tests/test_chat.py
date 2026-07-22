"""Testes do chat com os agentes do hub condominial."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.schemas.chat import ChatRequest, MensagemChat
from app.services.chat import gerar_resposta_stream
from app.services.drive import DriveEntry

AGENTES_ESPERADOS = {
    "supervisor",
    "notificacoes",
    "peticoes",
    "contratos",
    "pareceres",
    "consulta-historica",
    "juridico-geral",
}


class _FakeStream:
    """Simula o context manager de streaming do SDK da Anthropic."""

    def __init__(self, partes: list[str]) -> None:
        self._partes = partes
        self.text_stream: AsyncIterator[str] | None = None

    async def __aenter__(self) -> "_FakeStream":
        async def _gen() -> AsyncIterator[str]:
            for parte in self._partes:
                yield parte

        self.text_stream = _gen()
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _mock_anthropic_stream(partes: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_FakeStream(partes))
    client.close = AsyncMock()
    return client


def _resp_tool_use(destino: str) -> MagicMock:
    """Resposta da Anthropic com um bloco tool_use escolhendo um destino."""
    bloco = MagicMock()
    bloco.type = "tool_use"
    bloco.name = "rotear"
    bloco.input = {"especialista": destino}
    resposta = MagicMock()
    resposta.content = [bloco]
    return resposta


def _mock_supervisor_client(destino: str, partes: list[str]) -> MagicMock:
    """Client com roteamento (create) e resposta em streaming (stream)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_resp_tool_use(destino))
    client.messages.stream = MagicMock(return_value=_FakeStream(partes))
    client.close = AsyncMock()
    return client


def test_listar_agentes(client: TestClient) -> None:
    response = client.get("/api/agentes")

    assert response.status_code == 200
    corpo = response.json()
    assert {a["slug"] for a in corpo} == AGENTES_ESPERADOS
    assert corpo[0]["slug"] == "supervisor"  # primeiro contato
    for agente in corpo:
        assert agente["nome"]
        assert agente["descricao"]


def test_card_direto_nao_roteia(client: TestClient) -> None:
    """Clique num card (slug de especialista) faz stream direto, sem roteamento."""
    fake = _mock_anthropic_stream(["Excelência, ", "segue a petição."])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "peticoes",
            "mensagens": [{"role": "user", "content": "Petição de cobrança de cotas"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "Excelência, segue a petição."
    fake.messages.create.assert_not_called()
    assert "condominial" in fake.messages.stream.call_args.kwargs["system"].lower()


def test_supervisor_roteia_para_especialista(client: TestClient) -> None:
    """Mensagem ao supervisor é roteada (tool use) e a resposta do especialista é transmitida."""
    fake = _mock_supervisor_client("notificacoes", ["Notificação: ", "prezado condômino."])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "supervisor",
            "mensagens": [{"role": "user", "content": "cão sujou o elevador"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "Notificação: prezado condômino."
    fake.messages.create.assert_awaited_once()
    assert "notifica" in fake.messages.stream.call_args.kwargs["system"].lower()


def test_supervisor_trata_onboarding_diretamente(client: TestClient) -> None:
    """Se o roteamento devolve 'supervisor', a própria persona do supervisor responde."""
    fake = _mock_supervisor_client("supervisor", ["Olá! ", "vamos começar o onboarding."])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "supervisor",
            "mensagens": [{"role": "user", "content": "oi"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "Olá! vamos começar o onboarding."
    assert "onboarding" in fake.messages.stream.call_args.kwargs["system"].lower()


def test_chat_aceita_modelo_economico(client: TestClient) -> None:
    fake = _mock_anthropic_stream(["ok"])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "peticoes",
            "modelo": "claude-haiku-4-5-20251001",
            "mensagens": [{"role": "user", "content": "Prazo da execução?"}],
        },
    )

    assert response.status_code == 200
    assert fake.messages.stream.call_args.kwargs["model"] == "claude-haiku-4-5-20251001"


def test_chat_agente_desconhecido_retorna_404(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "agente": "inexistente",
            "mensagens": [{"role": "user", "content": "oi"}],
        },
    )

    assert response.status_code == 404


def test_chat_sem_mensagens_retorna_422(client: TestClient) -> None:
    response = client.post("/api/chat", json={"agente": "peticoes", "mensagens": []})

    assert response.status_code == 422


def test_chat_modelo_invalido_retorna_422(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "agente": "peticoes",
            "modelo": "gpt-4",
            "mensagens": [{"role": "user", "content": "oi"}],
        },
    )

    assert response.status_code == 422


def test_index_serve_interface(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "LexHub" in response.text


def test_index_tem_placeholders_do_escritorio(client: TestClient) -> None:
    """O front expõe os placeholders inertes de cliente e conexão Google."""
    html = client.get("/").text
    assert "Condomínio ativo" in html
    assert "Google Drive" in html


def test_proposta_acessivel_externamente(client: TestClient) -> None:
    """A proposta deve carregar mesmo quando o host é externo (tunnel)."""
    response = client.get("/proposta", headers={"host": "abc.trycloudflare.com"})

    assert response.status_code == 200
    assert "Wilker" in response.text


def test_chat_bloqueado_para_host_externo(client: TestClient) -> None:
    """Acessos de fora não podem usar o chat — proteção contra abuso de tokens."""
    response = client.post(
        "/api/chat",
        headers={"host": "abc.trycloudflare.com"},
        json={
            "agente": "juridico-geral",
            "mensagens": [{"role": "user", "content": "oi"}],
        },
    )

    assert response.status_code == 404


def test_index_bloqueado_para_host_externo(client: TestClient) -> None:
    """A interface do hub não fica exposta no tunnel."""
    response = client.get("/", headers={"host": "abc.trycloudflare.com"})

    assert response.status_code == 404


def test_hub_publico_libera_acesso_externo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com HUB_PUBLICO=true (deploy), o hub fica acessível para hosts externos."""
    from app import main
    from app.config import Settings

    monkeypatch.setattr(main, "get_settings", lambda: Settings(HUB_PUBLICO=True))  # type: ignore[call-arg]
    response = client.get("/", headers={"host": "lexhub.onrender.com"})

    assert response.status_code == 200
    assert "LexHub" in response.text


class _FakeDrive:
    """Leitor de Drive fake com uma pasta de modelos de parecer."""

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        if pasta_id == "acervo":
            return [DriveEntry(id="p1", nome="Modelo de Pareceres", is_folder=True)]
        if pasta_id == "p1":
            return [DriveEntry(id="a1", nome="parecer.docx", is_folder=False)]
        return []

    async def ler_texto(self, file_id: str) -> str:
        return "Corpo do modelo de parecer do escritório."


async def test_grounding_injeta_modelos_no_system() -> None:
    """Com conector + acervo, o especialista recebe os modelos no system."""
    fake = _mock_anthropic_stream(["ok"])
    payload = ChatRequest(
        agente="pareceres",
        mensagens=[MensagemChat(role="user", content="faça um parecer")],
    )

    trechos = [
        t
        async for t in gerar_resposta_stream(
            payload, fake, conector=_FakeDrive(), acervo_raiz="acervo"
        )
    ]

    assert trechos == ["ok"]
    system = fake.messages.stream.call_args.kwargs["system"]
    assert "MODELOS DO ESCRITÓRIO" in system
    assert "Corpo do modelo de parecer" in system


async def test_system_inclui_capacidade_de_opcoes() -> None:
    """Todo agente recebe a instrução para oferecer opções clicáveis."""
    fake = _mock_anthropic_stream(["ok"])
    payload = ChatRequest(
        agente="juridico-geral",
        mensagens=[MensagemChat(role="user", content="oi")],
    )

    async for _ in gerar_resposta_stream(payload, fake):
        pass

    system = fake.messages.stream.call_args.kwargs["system"]
    assert "[[OPCOES" in system


async def test_sem_conector_nao_injeta_referencia() -> None:
    """Sem conector, o system é apenas o prompt do agente (sem modelos)."""
    fake = _mock_anthropic_stream(["ok"])
    payload = ChatRequest(
        agente="pareceres",
        mensagens=[MensagemChat(role="user", content="faça um parecer")],
    )

    async for _ in gerar_resposta_stream(payload, fake):
        pass

    system = fake.messages.stream.call_args.kwargs["system"]
    assert "MODELOS DO ESCRITÓRIO" not in system
