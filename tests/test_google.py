"""Testes do router de conexão do Google Drive (Composio mockado)."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.dependencies_google import get_composio_client
from app.services.composio_drive import ConexaoLink


def test_status_nao_configurado(client: TestClient) -> None:
    client.app.dependency_overrides[get_composio_client] = lambda: None
    try:
        response = client.get("/api/google/status")
        assert response.status_code == 200
        assert response.json() == {"configurado": False, "conectado": False}
    finally:
        client.app.dependency_overrides.clear()


def test_status_conectado(client: TestClient) -> None:
    fake = MagicMock()
    fake.conexao_ativa = AsyncMock(return_value=True)
    client.app.dependency_overrides[get_composio_client] = lambda: fake
    try:
        response = client.get("/api/google/status")
        assert response.json() == {"configurado": True, "conectado": True}
    finally:
        client.app.dependency_overrides.clear()


def test_conectar_gera_link(client: TestClient) -> None:
    fake = MagicMock()
    fake.criar_link = AsyncMock(
        return_value=ConexaoLink(
            redirect_url="https://connect.composio.dev/link/lk_x",
            connected_account_id="ca_1",
        )
    )
    client.app.dependency_overrides[get_composio_client] = lambda: fake
    try:
        response = client.post("/api/google/conectar")
        assert response.status_code == 200
        assert response.json() == {"redirect_url": "https://connect.composio.dev/link/lk_x"}
        fake.criar_link.assert_awaited_once()
    finally:
        client.app.dependency_overrides.clear()


def test_conectar_sem_composio_retorna_503(client: TestClient) -> None:
    client.app.dependency_overrides[get_composio_client] = lambda: None
    try:
        response = client.post("/api/google/conectar")
        assert response.status_code == 503
    finally:
        client.app.dependency_overrides.clear()


def test_google_bloqueado_para_host_externo(client: TestClient) -> None:
    response = client.get("/api/google/status", headers={"host": "abc.trycloudflare.com"})
    assert response.status_code == 404
