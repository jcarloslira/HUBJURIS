"""Testes do módulo de Rifas."""

import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

# Token do Mercado Pago configurado para os testes (apenas pra classe ser importável)
os.environ.setdefault("MERCADO_PAGO_ACCESS_TOKEN", "APP_USR-test")


@pytest.fixture
def rifa_payload() -> dict:
    return {
        "titulo": "JBL Boombox 4",
        "subtitulo": "PARTICIPE E CONCORRA!",
        "descricao": "Sorteio auditado.",
        "imagem_url": None,
        "preco_por_numero": "0.20",
        "total_numeros": 100,
        "data_sorteio": "2030-01-01T20:00:00+00:00",
    }


def _install_table_mock(supabase_mock, rows):
    """Substitui `supabase_mock.table` por um mock sync encadeável; `execute()` é async."""
    from unittest.mock import AsyncMock, MagicMock

    chain_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=chain_mock)
    result_obj = type("R", (), {"data": rows})()
    # `execute()` precisa ser AsyncMock porque é awaited.
    chain_mock.select.return_value.in_.return_value.order.return_value.execute = AsyncMock(
        return_value=result_obj
    )
    chain_mock.select.return_value.eq.return_value.execute = AsyncMock(return_value=result_obj)
    chain_mock.update.return_value.eq.return_value.execute = AsyncMock(return_value=result_obj)
    chain_mock.insert.return_value.execute = AsyncMock(return_value=result_obj)
    return chain_mock


def test_router_exposto_no_openapi(client) -> None:
    """Tags das rotas de rifas aparecem no OpenAPI."""
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert any(p.startswith("/api/rifas") for p in paths), "rotas /api/rifas ausentes"


def test_listar_rifas_retorna_lista_quando_supabase_responde(
    client,
    supabase_mock,
    rifa_payload,
) -> None:
    """GET /api/rifas: retorna rifas ativas quando Supabase responde."""
    _install_table_mock(
        supabase_mock,
        [
            {
                "id": "rifa-1",
                "titulo": rifa_payload["titulo"],
                "subtitulo": rifa_payload["subtitulo"],
                "descricao": rifa_payload["descricao"],
                "imagem_url": None,
                "preco_por_numero": 0.20,
                "total_numeros": 100,
                "data_sorteio": "2030-01-01T20:00:00+00:00",
                "regulamento": None,
                "status": "ativa",
                "numero_sorteado": None,
                "ganhador_nome": None,
                "created_at": "2025-01-01T00:00:00+00:00",
            }
        ],
    )

    response = client.get("/api/rifas")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["titulo"] == "JBL Boombox 4"
    assert body[0]["status"] == "ativa"


def test_endpoint_sem_supabase_retorna_503(supabase_mock) -> None:
    """Quando o Supabase não está configurado, /api/rifas retorna 503."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from app import main

    with patch.object(main, "create_supabase_client", AsyncMock(return_value=None)):
        with TestClient(main.app) as no_client:
            no_client.headers["host"] = "localhost"
            r = no_client.get("/api/rifas")
            assert r.status_code == 503


def test_schema_pedido_valida_numeros_duplicados() -> None:
    """PedidoCreate rejeita números duplicados."""
    from pydantic import ValidationError

    from app.schemas.rifas import PedidoCreate

    with pytest.raises(ValidationError) as exc:
        PedidoCreate(
            rifa_id="rifa-1",
            numeros=[1, 2, 2, 3],
            comprador_nome="Maria",
            comprador_telefone="11999999999",
        )
    assert "duplicados" in str(exc.value)


def test_schema_pedido_aceita_payload_valido() -> None:
    """PedidoCreate aceita dados válidos."""
    from app.schemas.rifas import PedidoCreate

    p = PedidoCreate(
        rifa_id="rifa-1",
        numeros=[1, 2, 3],
        comprador_nome="Maria",
        comprador_telefone="11999999999",
        comprador_email="maria@example.com",
    )
    assert p.numeros == [1, 2, 3]


def test_pedido_response_pix_opcional() -> None:
    """PedidoResponse permite pix=None (modo sem MP)."""
    from app.schemas.rifas import PedidoResponse

    r = PedidoResponse(
        pedido_id="p1",
        rifa_id="r1",
        numeros=[1, 2, 3],
        valor_total=Decimal("0.60"),
        status="pendente",
        pix=None,
    )
    assert r.pix is None
    assert r.valor_total == Decimal("0.60")


def test_mercadopago_habilitado_quando_token_existe() -> None:
    """Cliente MP detecta token configurado."""
    from app.config import Settings
    from app.services.mercadopago import MercadoPagoClient

    s = Settings(MERCADO_PAGO_ACCESS_TOKEN="APP_USR-fake")
    c = MercadoPagoClient(s, AsyncMock())
    assert c.habilitado is True


def test_mercadopago_desabilitado_sem_token() -> None:
    """Cliente MP reporta desabilitado sem token."""
    from app.config import Settings
    from app.services.mercadopago import MercadoPagoClient

    s = Settings()
    s.MERCADO_PAGO_ACCESS_TOKEN = ""
    c = MercadoPagoClient(s, AsyncMock())
    assert c.habilitado is False


@pytest.mark.asyncio
async def test_mercadopago_criar_pix_sem_token_falha() -> None:
    """Criar Pix sem token configurado levanta erro claro."""
    from app.config import Settings
    from app.services.mercadopago import MercadoPagoClient, MercadoPagoError

    s = Settings()
    s.MERCADO_PAGO_ACCESS_TOKEN = ""
    c = MercadoPagoClient(s, AsyncMock())
    with pytest.raises(MercadoPagoError):
        await c.criar_pix(
            valor=Decimal("10.50"),
            descricao="Teste",
            referencia_externa="x",
            nome_pagador="Maria",
        )


def test_sorteio_response_basico() -> None:
    """SorteioResponse aceita data no passado e ganhador."""
    from app.schemas.rifas import SorteioResponse

    r = SorteioResponse(
        rifa_id="rifa-1",
        numero_sorteado=42,
        ganhador_nome="João",
        ganhador_telefone="11999999999",
        sorteado_em=datetime.now(UTC),
    )
    assert r.numero_sorteado == 42
    assert r.ganhador_nome == "João"
