"""Testes do conector do Google Drive via Composio (mockando a API HTTP)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.composio_drive import (
    ComposioClient,
    ComposioDriveConnector,
    ComposioError,
)

_BASE = "https://backend.composio.dev/api/v3"


class _Resp:
    """Resposta HTTP simulada (httpx-like)."""

    def __init__(
        self, json_data: dict[str, Any] | None = None, status_code: int = 200, text: str = ""
    ) -> None:
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json


def _client(http: MagicMock) -> ComposioClient:
    return ComposioClient(http, api_key="k", base_url=_BASE, auth_config_id="ac_1")


def _http() -> MagicMock:
    http = MagicMock()
    http.post = AsyncMock()
    http.get = AsyncMock()
    return http


async def test_criar_link() -> None:
    http = _http()
    http.post.return_value = _Resp(
        {"redirect_url": "https://connect.composio.dev/link/lk_1", "connected_account_id": "ca_1"},
        status_code=201,
    )

    link = await _client(http).criar_link("escritorio-1")

    assert link.redirect_url == "https://connect.composio.dev/link/lk_1"
    assert link.connected_account_id == "ca_1"
    assert http.post.call_args.kwargs["json"] == {
        "auth_config_id": "ac_1",
        "user_id": "escritorio-1",
    }


async def test_criar_link_erro_vira_exception() -> None:
    http = _http()
    http.post.return_value = _Resp({"error": "bad"}, status_code=400)

    with pytest.raises(ComposioError):
        await _client(http).criar_link("escritorio-1")


async def test_conexao_ativa() -> None:
    http = _http()
    http.get.return_value = _Resp({"items": [{"status": "ACTIVE"}]})
    assert await _client(http).conexao_ativa("escritorio-1") is True

    http.get.return_value = _Resp({"items": []})
    assert await _client(http).conexao_ativa("escritorio-1") is False


async def test_listar_filhos_separa_pastas_e_arquivos() -> None:
    http = _http()
    http.post.return_value = _Resp(
        {
            "successful": True,
            "data": {
                "files": [
                    {
                        "id": "d1",
                        "name": "Modelo de Pareceres",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                    {"id": "f1", "name": "parecer.docx", "mimeType": "application/msword"},
                ]
            },
        }
    )

    filhos = await _client(http).listar_filhos("escritorio-1", "root")

    assert [(e.nome, e.is_folder) for e in filhos] == [
        ("Modelo de Pareceres", True),
        ("parecer.docx", False),
    ]
    corpo = http.post.call_args.kwargs["json"]
    assert corpo["user_id"] == "escritorio-1"
    assert "'root' in parents" in corpo["arguments"]["q"]


async def test_execute_sem_sucesso_lanca_erro() -> None:
    http = _http()
    http.post.return_value = _Resp({"successful": False, "error": "File not found"})

    with pytest.raises(ComposioError):
        await _client(http).listar_filhos("escritorio-1", "x")


async def test_ler_texto_baixa_do_s3url() -> None:
    http = _http()
    http.post.return_value = _Resp(
        {"successful": True, "data": {"file": {"s3url": "https://s3/x", "name": "p.docx"}}}
    )
    http.get.return_value = _Resp(text="Parecer no estilo do escritório.")

    texto = await _client(http).ler_texto("escritorio-1", "f1")

    assert texto == "Parecer no estilo do escritório."
    http.get.assert_awaited_once_with("https://s3/x")


async def test_connector_fixa_user_id() -> None:
    http = _http()
    http.post.return_value = _Resp({"successful": True, "data": {"files": []}})
    conector = ComposioDriveConnector(_client(http), "escritorio-99")

    await conector.listar_filhos("root")

    assert http.post.call_args.kwargs["json"]["user_id"] == "escritorio-99"
