"""Testes da lógica de contas (auth, equipe, uso) com httpx + Supabase mockados."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.schemas.contas import LoginPayload, SignupPayload
from app.services.contas import ContaError, ContaService


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        SUPABASE_URL="https://x.supabase.co",
        SUPABASE_ANON_KEY="anon-key",
        SUPABASE_SERVICE_ROLE_KEY="service-key",
    )


class _Resp:
    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self._d = data
        self.status_code = status

    def json(self) -> dict[str, Any]:
        return self._d


class _Res:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, fila: list[list[dict[str, Any]]]) -> None:
        self._fila = fila

    def select(self, *a: object, **k: object) -> "_Query":
        return self

    def insert(self, *a: object, **k: object) -> "_Query":
        return self

    def eq(self, *a: object, **k: object) -> "_Query":
        return self

    def order(self, *a: object, **k: object) -> "_Query":
        return self

    def limit(self, *a: object, **k: object) -> "_Query":
        return self

    async def execute(self) -> _Res:
        return _Res(self._fila.pop(0) if self._fila else [])


class _FakeDB:
    def __init__(self, tabelas: dict[str, list[list[dict[str, Any]]]]) -> None:
        self._t = {nome: list(fila) for nome, fila in tabelas.items()}

    def table(self, nome: str) -> _Query:
        return _Query(self._t.setdefault(nome, []))


async def test_signup_cria_usuario_escritorio_e_sessao() -> None:
    http = MagicMock()
    http.post = AsyncMock(side_effect=[_Resp({"id": "u1"}), _Resp({"access_token": "tok123"})])
    db = _FakeDB({"escritorios": [[{"id": "esc1"}]], "membros": [[{"user_id": "u1"}]]})
    svc = ContaService(db, http, _settings())  # type: ignore[arg-type]

    sessao = await svc.signup(
        SignupPayload(
            nome="Dr. Teste", email="a@b.com", senha="senha12345", nome_escritorio="Escritório X"
        )
    )

    assert sessao.access_token == "tok123"
    assert sessao.perfil.papel == "admin"
    assert sessao.perfil.escritorio_nome == "Escritório X"
    assert sessao.perfil.escritorio_id == "esc1"


async def test_signup_email_duplicado_vira_409() -> None:
    http = MagicMock()
    http.post = AsyncMock(return_value=_Resp({"msg": "already registered"}, 422))
    svc = ContaService(_FakeDB({}), http, _settings())  # type: ignore[arg-type]

    with pytest.raises(ContaError) as exc:
        await svc.signup(
            SignupPayload(
                nome="Zé Teste", email="a@b.com", senha="senha12345", nome_escritorio="Yз"
            )
        )
    assert exc.value.status == 409


async def test_login_credenciais_invalidas_vira_401() -> None:
    http = MagicMock()
    http.post = AsyncMock(return_value=_Resp({"error": "invalid"}, 400))
    svc = ContaService(_FakeDB({}), http, _settings())  # type: ignore[arg-type]

    with pytest.raises(ContaError) as exc:
        await svc.login(LoginPayload(email="a@b.com", senha="x"))
    assert exc.value.status == 401


async def test_sem_conexao_vira_503() -> None:
    import httpx

    http = MagicMock()
    http.post = AsyncMock(side_effect=httpx.ConnectError("getaddrinfo failed"))
    svc = ContaService(_FakeDB({}), http, _settings())  # type: ignore[arg-type]

    with pytest.raises(ContaError) as exc:
        await svc.login(LoginPayload(email="a@b.com", senha="x"))
    assert exc.value.status == 503


async def test_resumo_uso_agrupa_por_modelo() -> None:
    db = _FakeDB(
        {
            "uso_tokens": [
                [
                    {"modelo": "claude-sonnet-4-6", "tokens_entrada": 100, "tokens_saida": 200},
                    {"modelo": "claude-sonnet-4-6", "tokens_entrada": 50, "tokens_saida": 10},
                    {"modelo": "claude-haiku-4-5-20251001", "tokens_entrada": 5, "tokens_saida": 5},
                ]
            ]
        }
    )
    svc = ContaService(db, MagicMock(), _settings())  # type: ignore[arg-type]

    resumo = await svc.resumo_uso("esc1")

    assert resumo.total_entrada == 155
    assert resumo.total_saida == 215
    por_modelo = {m.modelo: (m.tokens_entrada, m.tokens_saida) for m in resumo.por_modelo}
    assert por_modelo["claude-sonnet-4-6"] == (150, 210)
    assert por_modelo["claude-haiku-4-5-20251001"] == (5, 5)
