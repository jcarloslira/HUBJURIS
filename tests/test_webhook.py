"""Testes do webhook da Evolution API."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.schemas.webhook import EvolutionMessageData


class TestEvolutionWebhookPayload:
    """Testes de parsing do payload."""

    def test_extrair_texto_simples(self) -> None:
        data = EvolutionMessageData(
            key={"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
            message={"conversation": "Oi, preciso de ajuda"},
        )
        assert data.extrair_texto() == "Oi, preciso de ajuda"

    def test_extrair_texto_estendido(self) -> None:
        data = EvolutionMessageData(
            key={"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
            message={
                "extendedTextMessage": {"text": "Texto com link"},
            },
        )
        assert data.extrair_texto() == "Texto com link"

    def test_extrair_texto_sem_mensagem(self) -> None:
        data = EvolutionMessageData(
            key={"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
            message=None,
        )
        assert data.extrair_texto() is None

    def test_extrair_telefone(self) -> None:
        data = EvolutionMessageData(
            key={"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
        )
        assert data.extrair_telefone() == "5511999999999"


class TestWebhookEndpoint:
    """Testes do endpoint webhook."""

    def test_ignora_evento_nao_messages(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "connection.update",
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": False,
                    },
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_ignora_mensagem_propria(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": True,
                    },
                    "message": {"conversation": "resposta do bot"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "from_me"

    def test_ignora_mensagem_sem_texto(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "no_text"

    def test_ignora_mensagem_de_grupo(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "120363xxxxx@g.us",
                        "fromMe": False,
                    },
                    "message": {"conversation": "msg de grupo"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "group_message"

    def test_processa_mensagem_valida(self, client: TestClient) -> None:
        client.app.state.supabase = AsyncMock()
        client.app.state.http_client = AsyncMock()

        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "pushName": "João",
                    "message": {"conversation": "Oi, tenho dívidas"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_retorna_erro_sem_supabase(self, client: TestClient) -> None:
        client.app.state.supabase = None

        response = client.post(
            "/api/webhook/evolution",
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {"conversation": "oi"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "supabase_not_configured"
