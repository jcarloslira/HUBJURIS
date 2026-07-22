"""Testes da config de agentes no banco: service, seed, fallback e override."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.schemas.agentes import AgenteConfig, AgenteConfigUpdate
from app.schemas.chat import ChatRequest, MensagemChat
from app.services.agentes_config import AgenteConfigError, AgenteConfigService
from app.services.chat import configs_padrao, gerar_resposta_stream

_LINHA = {
    "slug": "pareceres",
    "nome": "Pareceres",
    "descricao": "Pareceres condominiais",
    "icone": "scroll",
    "system_prompt": "Prompt do banco",
    "modelo": "claude-sonnet-4-6",
    "max_tokens": 1024,
    "ativo": True,
    "ordem": 4,
}


# ── Fakes do Supabase ───────────────────────────────────────────


class _Res:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    def __init__(self, nome: str, fila: list[list[dict[str, Any]]], db: "_FakeDB") -> None:
        self._nome = nome
        self._fila = fila
        self._db = db
        self._op: str | None = None

    def select(self, *a: object, **k: object) -> "_Query":
        return self

    def insert(self, dados: dict[str, Any]) -> "_Query":
        self._op = "insert"
        self._db.inserts.append((self._nome, dados))
        return self

    def update(self, dados: dict[str, Any]) -> "_Query":
        self._op = "update"
        return self

    def eq(self, *a: object, **k: object) -> "_Query":
        return self

    def order(self, *a: object, **k: object) -> "_Query":
        return self

    async def execute(self) -> _Res:
        return _Res(self._fila.pop(0) if self._fila else [])


class _FakeDB:
    def __init__(self, tabelas: dict[str, list[list[dict[str, Any]]]]) -> None:
        self._t = {n: list(f) for n, f in tabelas.items()}
        self.inserts: list[tuple[str, dict[str, Any]]] = []

    def table(self, nome: str) -> _Query:
        return _Query(nome, self._t.setdefault(nome, []), self)


# ── Service ─────────────────────────────────────────────────────


async def test_listar_valida_linhas_do_banco() -> None:
    svc = AgenteConfigService(_FakeDB({"agentes_config": [[_LINHA]]}))  # type: ignore[arg-type]
    configs = await svc.listar()
    assert len(configs) == 1
    assert configs[0].slug == "pareceres"
    assert configs[0].system_prompt == "Prompt do banco"


async def test_listar_degrada_para_vazio() -> None:
    db = MagicMock()
    db.table.side_effect = RuntimeError("sem banco")
    svc = AgenteConfigService(db)
    assert await svc.listar() == []


async def test_atualizar_devolve_config_nova() -> None:
    nova = {**_LINHA, "system_prompt": "Prompt editado"}
    svc = AgenteConfigService(_FakeDB({"agentes_config": [[nova]]}))  # type: ignore[arg-type]
    cfg = await svc.atualizar("pareceres", AgenteConfigUpdate(system_prompt="Prompt editado"))
    assert cfg.system_prompt == "Prompt editado"


async def test_atualizar_inexistente_vira_404() -> None:
    svc = AgenteConfigService(_FakeDB({"agentes_config": [[]]}))  # type: ignore[arg-type]
    with pytest.raises(AgenteConfigError) as exc:
        await svc.atualizar("fantasma", AgenteConfigUpdate(system_prompt="x"))
    assert exc.value.status == 404


async def test_seed_insere_apenas_os_faltantes() -> None:
    existentes = [{"slug": "supervisor"}, {"slug": "notificacoes"}]
    db = _FakeDB({"agentes_config": [existentes]})
    svc = AgenteConfigService(db)  # type: ignore[arg-type]

    await svc.seed_defaults(configs_padrao())

    inseridos = {dados["slug"] for _, dados in db.inserts}
    assert "supervisor" not in inseridos and "notificacoes" not in inseridos
    assert "pareceres" in inseridos and "peticoes" in inseridos
    assert len(db.inserts) == len(configs_padrao()) - 2


def test_configs_padrao_cobre_o_registro() -> None:
    padroes = configs_padrao()
    slugs = {c.slug for c in padroes}
    assert "supervisor" in slugs
    assert len(padroes) == 7
    assert all(c.system_prompt for c in padroes)


# ── Override no chat ────────────────────────────────────────────


class _FakeStream:
    def __init__(self, partes: list[str]) -> None:
        self._partes = partes
        self.text_stream: AsyncIterator[str] | None = None

    async def __aenter__(self) -> "_FakeStream":
        async def _gen() -> AsyncIterator[str]:
            for parte in self._partes:
                yield parte

        self.text_stream = _gen()
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False


async def test_chat_aplica_config_do_banco() -> None:
    fake = MagicMock()
    fake.messages.stream = MagicMock(return_value=_FakeStream(["ok"]))
    payload = ChatRequest(
        agente="pareceres",
        mensagens=[MensagemChat(role="user", content="oi")],
    )
    configs = {
        "pareceres": AgenteConfig(
            slug="pareceres",
            nome="Pareceres",
            system_prompt="PROMPT CUSTOMIZADO DO BANCO",
            modelo="claude-haiku-4-5-20251001",
            max_tokens=512,
        )
    }

    trechos = [t async for t in gerar_resposta_stream(payload, fake, configs=configs)]

    assert trechos == ["ok"]
    chamada = fake.messages.stream.call_args.kwargs
    assert chamada["system"].startswith("PROMPT CUSTOMIZADO DO BANCO")
    assert chamada["model"] == "claude-haiku-4-5-20251001"
    assert chamada["max_tokens"] == 512


# ── Fallback do endpoint admin ──────────────────────────────────


def test_admin_agentes_cai_no_padrao_sem_banco(client: TestClient) -> None:
    """GET /api/admin/agentes devolve os padrões do código quando o banco não tem linhas."""
    response = client.get("/api/admin/agentes")
    assert response.status_code == 200
    corpo = response.json()
    assert {a["slug"] for a in corpo} >= {"supervisor", "pareceres"}
