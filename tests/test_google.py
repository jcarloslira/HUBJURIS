"""Testes do router do Google Drive multi-tenant (auth + escritório mockados)."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user
from app.routers.contas import get_conta_service
from app.routers.google import get_google_service
from app.schemas.auth import AuthUser
from app.schemas.contas import PerfilResponse
from app.schemas.google import PastaDrive, StatusDrive
from app.services.google_escritorio import GoogleEscritorioError


def _perfil() -> PerfilResponse:
    return PerfilResponse(
        user_id="u1",
        nome="Dr. Teste",
        email="dr@esc.adv.br",
        papel="admin",
        escritorio_id="esc1",
        escritorio_nome="Escritório Teste",
    )


@pytest.fixture
def google(client: TestClient) -> Iterator[MagicMock]:
    """Client autenticado (usuário do esc1) com o service do Drive mockado."""
    svc = MagicMock()
    client.app.dependency_overrides[get_current_user] = lambda: AuthUser(id="u1", email="dr@x")
    contas = MagicMock()
    contas.perfil = AsyncMock(return_value=_perfil())
    client.app.dependency_overrides[get_conta_service] = lambda: contas
    client.app.dependency_overrides[get_google_service] = lambda: svc
    try:
        yield svc
    finally:
        client.app.dependency_overrides.clear()


def test_status_escopado_ao_escritorio(client: TestClient, google: MagicMock) -> None:
    google.status = AsyncMock(
        return_value=StatusDrive(
            configurado=True, conectado=True, acervo_definido=True, acervo_folder_id="f1"
        )
    )
    response = client.get("/api/google/status")

    assert response.status_code == 200
    body = response.json()
    assert body["conectado"] is True and body["acervo_folder_id"] == "f1"
    google.status.assert_awaited_once_with("esc1")


def test_status_nao_configurado(client: TestClient, google: MagicMock) -> None:
    google.status = AsyncMock(return_value=StatusDrive(configurado=False, conectado=False))
    response = client.get("/api/google/status")

    assert response.status_code == 200
    assert response.json()["configurado"] is False


def test_conectar_gera_link(client: TestClient, google: MagicMock) -> None:
    google.link = AsyncMock(return_value="https://connect.composio.dev/link/lk_x")
    response = client.post("/api/google/conectar")

    assert response.status_code == 200
    assert response.json() == {"redirect_url": "https://connect.composio.dev/link/lk_x"}
    google.link.assert_awaited_once_with("esc1")


def test_conectar_sem_composio_retorna_503(client: TestClient, google: MagicMock) -> None:
    google.link = AsyncMock(side_effect=GoogleEscritorioError("sem composio", status=503))
    response = client.post("/api/google/conectar")

    assert response.status_code == 503


def test_listar_pastas(client: TestClient, google: MagicMock) -> None:
    google.listar_pastas = AsyncMock(return_value=[PastaDrive(id="p1", nome="Petições")])
    response = client.get("/api/google/pastas")

    assert response.status_code == 200
    assert response.json() == [{"id": "p1", "nome": "Petições"}]


def test_definir_acervo(client: TestClient, google: MagicMock) -> None:
    google.definir_acervo = AsyncMock(return_value=None)
    response = client.put("/api/google/acervo", json={"folder_id": "folder-9"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    google.definir_acervo.assert_awaited_once_with("esc1", "folder-9")


def test_status_exige_login(client: TestClient) -> None:
    """Sem token, o endpoint do Drive é 401 — não é mais aberto por ADMIN_TOKEN."""
    response = client.get("/api/google/status")
    assert response.status_code in (401, 403)


def test_google_bloqueado_para_host_externo(client: TestClient) -> None:
    response = client.get("/api/google/status", headers={"host": "abc.trycloudflare.com"})
    assert response.status_code == 404
