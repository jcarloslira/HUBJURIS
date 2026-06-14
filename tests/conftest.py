"""Fixtures compartilhadas dos testes."""

import os
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# Env fake antes de qualquer import da app — os testes nunca tocam serviços reais.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("EVOLUTION_API_URL", "https://test-evolution.com")
os.environ.setdefault("EVOLUTION_API_KEY", "test-evolution-key")
os.environ.setdefault("EVOLUTION_INSTANCE", "test-instance")


@pytest.fixture
def supabase_mock() -> AsyncMock:
    """Mock do cliente Supabase assíncrono."""
    return AsyncMock()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, supabase_mock: AsyncMock) -> Iterator[TestClient]:
    """TestClient da app com Supabase mockado no lifespan."""
    from app import main

    monkeypatch.setattr(main, "create_supabase_client", AsyncMock(return_value=supabase_mock))
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Headers de autenticação com token fake para testes."""
    return {"Authorization": "Bearer token-de-teste"}
