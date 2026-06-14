"""Testes do chat com os agentes do hub."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

AGENTES_ESPERADOS = {"juridico-geral", "peticoes", "processos", "contratos"}


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


def test_listar_agentes(client: TestClient) -> None:
    response = client.get("/api/agentes")

    assert response.status_code == 200
    corpo = response.json()
    assert {a["slug"] for a in corpo} == AGENTES_ESPERADOS
    for agente in corpo:
        assert agente["nome"]
        assert agente["descricao"]


def test_chat_retorna_resposta_em_streaming(client: TestClient) -> None:
    fake = _mock_anthropic_stream(["Excelência, ", "segue a petição."])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "peticoes",
            "mensagens": [{"role": "user", "content": "Redija uma petição inicial"}],
        },
    )

    assert response.status_code == 200
    assert response.text == "Excelência, segue a petição."
    kwargs = fake.messages.stream.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 8192
    assert "peças processuais" in kwargs["system"]


def test_chat_aceita_modelo_economico(client: TestClient) -> None:
    fake = _mock_anthropic_stream(["ok"])
    client.app.state.anthropic = fake

    response = client.post(
        "/api/chat",
        json={
            "agente": "juridico-geral",
            "modelo": "claude-haiku-4-5-20251001",
            "mensagens": [{"role": "user", "content": "Prazo da apelação?"}],
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
