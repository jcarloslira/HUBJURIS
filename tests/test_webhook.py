"""Testes do webhook da W-API."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.schemas.webhook import WAPIMessageData


class TestWAPIPayloadParsing:
    """Testes de parsing do payload."""

    def test_extrair_texto_campo_body(self) -> None:
        data = WAPIMessageData(body="Oi, preciso de ajuda")
        assert data.extrair_texto() == "Oi, preciso de ajuda"

    def test_extrair_texto_campo_text(self) -> None:
        data = WAPIMessageData(text="Texto direto")
        assert data.extrair_texto() == "Texto direto"

    def test_extrair_texto_conversation(self) -> None:
        data = WAPIMessageData(
            message={"conversation": "Via conversation"},
        )
        assert data.extrair_texto() == "Via conversation"

    def test_extrair_texto_sem_mensagem(self) -> None:
        data = WAPIMessageData()
        assert data.extrair_texto() is None

    def test_extrair_telefone_campo_phone(self) -> None:
        data = WAPIMessageData(phone="5511999999999")
        assert data.extrair_telefone() == "5511999999999"

    def test_extrair_telefone_campo_number(self) -> None:
        data = WAPIMessageData(number="+55 11 99999-9999")
        assert data.extrair_telefone() == "5511999999999"

    def test_extrair_telefone_remote_jid(self) -> None:
        data = WAPIMessageData(
            key={"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
        )
        assert data.extrair_telefone() == "5511999999999"

    def test_extrair_telefone_sem_dados(self) -> None:
        data = WAPIMessageData()
        assert data.extrair_telefone() is None

    def test_eh_grupo(self) -> None:
        data = WAPIMessageData(
            key={"remoteJid": "120363xxxxx@g.us", "fromMe": False},
        )
        assert data.eh_grupo() is True

    def test_nao_eh_grupo(self) -> None:
        data = WAPIMessageData(phone="5511999999999")
        assert data.eh_grupo() is False


class TestWebhookEndpoint:
    """Testes do endpoint webhook."""

    def test_ignora_mensagem_propria(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/wapi",
            json={
                "data": {
                    "key": {
                        "remoteJid": "5511999999999@s.whatsapp.net",
                        "fromMe": True,
                    },
                    "body": "resposta do bot",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "from_me"

    def test_ignora_mensagem_sem_texto(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/wapi",
            json={"data": {"phone": "5511999999999"}},
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "no_text"

    def test_ignora_mensagem_de_grupo(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/wapi",
            json={
                "data": {
                    "key": {
                        "remoteJid": "120363xxxxx@g.us",
                        "fromMe": False,
                    },
                    "body": "msg de grupo",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "group_message"

    def test_ignora_sem_telefone(self, client: TestClient) -> None:
        response = client.post(
            "/api/webhook/wapi",
            json={"data": {"body": "oi"}},
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "no_phone"

    def test_processa_mensagem_formato_data(self, client: TestClient) -> None:
        client.app.state.supabase = AsyncMock()
        client.app.state.http_client = AsyncMock()

        response = client.post(
            "/api/webhook/wapi",
            json={
                "data": {
                    "phone": "5511999999999",
                    "name": "João",
                    "body": "Oi, tenho dívidas",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_processa_mensagem_formato_raiz(self, client: TestClient) -> None:
        client.app.state.supabase = AsyncMock()
        client.app.state.http_client = AsyncMock()

        response = client.post(
            "/api/webhook/wapi",
            json={
                "phone": "5562999999999",
                "name": "Maria",
                "body": "Preciso de ajuda com dívidas",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "processing"

    def test_retorna_erro_sem_supabase(self, client: TestClient) -> None:
        client.app.state.supabase = None

        response = client.post(
            "/api/webhook/wapi",
            json={
                "data": {
                    "phone": "5511999999999",
                    "body": "oi",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["reason"] == "supabase_not_configured"
