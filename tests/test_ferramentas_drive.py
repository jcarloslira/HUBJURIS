"""Testes das ferramentas de Drive dos agentes (handlers com Composio mockado)."""

from unittest.mock import AsyncMock

import pytest

from app.agents.ferramentas_drive import (
    FERRAMENTAS_DRIVE,
    NOMES_DRIVE,
    montar_handlers_drive,
)
from app.services.composio_drive import ComposioError
from app.services.drive import DriveEntry


def test_schemas_e_nomes_batem() -> None:
    nomes = {f["name"] for f in FERRAMENTAS_DRIVE}
    assert nomes == NOMES_DRIVE
    assert "buscar_no_drive" in nomes and "salvar_no_drive" in nomes


@pytest.mark.asyncio
async def test_buscar_formata_resultados() -> None:
    composio = AsyncMock()
    composio.executar_acao.return_value = {
        "files": [
            {"id": "1", "name": "Notificação Bloco B", "mimeType": "application/pdf"},
            {"id": "2", "name": "Modelos", "mimeType": "application/vnd.google-apps.folder"},
        ]
    }
    handlers = montar_handlers_drive(composio, "escr-1")
    saida = await handlers["buscar_no_drive"]({"termo": "notificação"})
    assert "Notificação Bloco B" in saida and "id: 1" in saida
    assert "pasta" in saida  # a pasta "Modelos" aparece classificada
    # a busca usa LIST_FILES escopada ao escritório
    assert composio.executar_acao.call_args.args[1] == "escr-1"


@pytest.mark.asyncio
async def test_listar_pasta_usa_root_por_padrao() -> None:
    composio = AsyncMock()
    composio.listar_filhos.return_value = [
        DriveEntry(id="9", nome="Convenção.docx", is_folder=False, mime="x")
    ]
    handlers = montar_handlers_drive(composio, "escr-1")
    saida = await handlers["listar_pasta_drive"]({})
    composio.listar_filhos.assert_awaited_once_with("escr-1", "root")
    assert "Convenção.docx" in saida


@pytest.mark.asyncio
async def test_salvar_no_drive_envia_conteudo() -> None:
    composio = AsyncMock()
    composio.executar_acao.return_value = {"id": "novo-123"}
    handlers = montar_handlers_drive(composio, "escr-1")
    saida = await handlers["salvar_no_drive"](
        {"nome_arquivo": "Notificação Apt 42", "conteudo": "NOTIFICAÇÃO..."}
    )
    tool, user_id, args = composio.executar_acao.call_args.args
    assert tool == "GOOGLEDRIVE_CREATE_FILE_FROM_TEXT"
    assert user_id == "escr-1"
    assert args["file_name"] == "Notificação Apt 42"
    assert "novo-123" in saida


@pytest.mark.asyncio
async def test_drive_desconectado_orienta_conectar() -> None:
    composio = AsyncMock()
    composio.executar_acao.side_effect = ComposioError("No connected account found for user")
    handlers = montar_handlers_drive(composio, "escr-1")
    saida = await handlers["buscar_no_drive"]({"termo": "x"})
    assert "não está conectado" in saida.lower()
    assert "conectores" in saida.lower()
