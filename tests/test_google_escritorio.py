"""Testes do Drive por escritório (Composio multi-tenant)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.composio_drive import ConexaoLink
from app.services.drive import DriveEntry
from app.services.google_escritorio import GoogleEscritorioError, GoogleEscritorioService


class _Res:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, fila: list[list[dict[str, Any]]]) -> None:
        self._fila = fila

    def select(self, *a: object, **k: object) -> "_Query":
        return self

    def update(self, *a: object, **k: object) -> "_Query":
        return self

    def eq(self, *a: object, **k: object) -> "_Query":
        return self

    def limit(self, *a: object, **k: object) -> "_Query":
        return self

    async def execute(self) -> _Res:
        return _Res(self._fila.pop(0) if self._fila else [])


class _FakeDB:
    def __init__(self, tabelas: dict[str, list[list[dict[str, Any]]]]) -> None:
        self._t = {n: list(f) for n, f in tabelas.items()}

    def table(self, nome: str) -> _Query:
        return _Query(self._t.setdefault(nome, []))


async def test_status_sem_composio() -> None:
    svc = GoogleEscritorioService(_FakeDB({}), None)  # type: ignore[arg-type]
    status = await svc.status("esc1")
    assert status.configurado is False
    assert status.conectado is False


async def test_status_conectado_com_acervo() -> None:
    composio = MagicMock()
    composio.conexao_ativa = AsyncMock(return_value=True)
    db = _FakeDB({"escritorios": [[{"acervo_folder_id": "folder-123"}]]})
    svc = GoogleEscritorioService(db, composio)  # type: ignore[arg-type]

    status = await svc.status("esc1")

    assert status.configurado is True
    assert status.conectado is True
    assert status.acervo_definido is True
    assert status.acervo_folder_id == "folder-123"
    composio.conexao_ativa.assert_awaited_once_with("esc1")


async def test_status_falha_de_conexao_nao_derruba() -> None:
    composio = MagicMock()
    composio.conexao_ativa = AsyncMock(side_effect=RuntimeError("timeout"))
    db = _FakeDB({"escritorios": [[{"acervo_folder_id": None}]]})
    svc = GoogleEscritorioService(db, composio)  # type: ignore[arg-type]

    status = await svc.status("esc1")

    assert status.conectado is False
    assert status.acervo_definido is False


async def test_listar_pastas_filtra_apenas_pastas() -> None:
    composio = MagicMock()
    composio.listar_filhos = AsyncMock(
        return_value=[
            DriveEntry(id="p1", nome="Petições", is_folder=True),
            DriveEntry(id="a1", nome="contrato.docx", is_folder=False),
            DriveEntry(id="p2", nome="Pareceres", is_folder=True),
        ]
    )
    svc = GoogleEscritorioService(_FakeDB({}), composio)  # type: ignore[arg-type]

    pastas = await svc.listar_pastas("esc1")

    assert [p.nome for p in pastas] == ["Petições", "Pareceres"]
    composio.listar_filhos.assert_awaited_once_with("esc1", "root")


async def test_acervo_de_le_a_pasta() -> None:
    db = _FakeDB({"escritorios": [[{"acervo_folder_id": "acervo-xyz"}]]})
    svc = GoogleEscritorioService(db, None)  # type: ignore[arg-type]
    assert await svc.acervo_de("esc1") == "acervo-xyz"


async def test_link_sem_composio_vira_503() -> None:
    svc = GoogleEscritorioService(_FakeDB({}), None)  # type: ignore[arg-type]
    with pytest.raises(GoogleEscritorioError) as exc:
        await svc.link("esc1")
    assert exc.value.status == 503


async def test_link_usa_o_escritorio_como_identidade() -> None:
    composio = MagicMock()
    composio.criar_link = AsyncMock(
        return_value=ConexaoLink(redirect_url="https://x/oauth", connected_account_id="c1")
    )
    svc = GoogleEscritorioService(_FakeDB({}), composio)  # type: ignore[arg-type]

    url = await svc.link("esc42")

    assert url == "https://x/oauth"
    composio.criar_link.assert_awaited_once_with("esc42")
