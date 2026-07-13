"""Testes da Espinha condominial (escritório, condomínios, blocos, unidades)."""

from typing import Any

from fastapi.testclient import TestClient


class _Res:
    """Resposta simulada do supabase-py (expõe .data)."""

    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _Query:
    """Query builder fake: encadeia e devolve o próximo resultado da fila."""

    def __init__(self, fila: list[list[dict[str, Any]]]) -> None:
        self._fila = fila

    def select(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def insert(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def update(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def eq(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def order(self, *args: object, **kwargs: object) -> "_Query":
        return self

    def limit(self, *args: object, **kwargs: object) -> "_Query":
        return self

    async def execute(self) -> _Res:
        data = self._fila.pop(0) if self._fila else []
        return _Res(data)


class _FakeSupabase:
    """Supabase fake: uma fila FIFO de resultados por tabela."""

    def __init__(self, tabelas: dict[str, list[list[dict[str, Any]]]]) -> None:
        self._tabelas = {nome: list(fila) for nome, fila in tabelas.items()}

    def table(self, nome: str) -> _Query:
        return _Query(self._tabelas.setdefault(nome, []))


def test_criar_condominio(client: TestClient) -> None:
    client.app.state.supabase = _FakeSupabase(
        {
            "escritorios": [[{"id": "esc-1"}]],
            "condominios": [[{"id": "c1", "nome": "Residencial Aurora", "status": "ativo"}]],
        }
    )

    response = client.post("/api/condominios", json={"nome": "Residencial Aurora"})

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["id"] == "c1"
    assert corpo["nome"] == "Residencial Aurora"
    assert corpo["status"] == "ativo"


def test_listar_condominios(client: TestClient) -> None:
    client.app.state.supabase = _FakeSupabase(
        {
            "condominios": [
                [
                    {"id": "c1", "nome": "Residencial Aurora", "status": "ativo"},
                    {"id": "c2", "nome": "Edifício Bela Vista", "status": "ativo"},
                ]
            ]
        }
    )

    response = client.get("/api/condominios")

    assert response.status_code == 200
    assert [c["nome"] for c in response.json()] == ["Residencial Aurora", "Edifício Bela Vista"]


def test_upsert_escritorio_cria_quando_nao_existe(client: TestClient) -> None:
    client.app.state.supabase = _FakeSupabase(
        {
            # 1ª execução (select id) vazia → cai no insert (2ª execução)
            "escritorios": [[], [{"id": "esc-1", "nome": "Jales Advocacia"}]],
        }
    )

    response = client.put(
        "/api/escritorio",
        json={"nome": "Jales Advocacia", "site": "https://jales.adv.br"},
    )

    assert response.status_code == 200
    assert response.json()["nome"] == "Jales Advocacia"


def test_criar_bloco(client: TestClient) -> None:
    client.app.state.supabase = _FakeSupabase(
        {"blocos": [[{"id": "b1", "condominio_id": "c1", "nome": "Bloco A"}]]}
    )

    response = client.post("/api/condominios/c1/blocos", json={"nome": "Bloco A"})

    assert response.status_code == 201
    assert response.json() == {"id": "b1", "condominio_id": "c1", "nome": "Bloco A"}


def test_condominios_bloqueado_para_host_externo(client: TestClient) -> None:
    """Endpoints do escritório não ficam expostos no tunnel — dado sensível."""
    response = client.get("/api/condominios", headers={"host": "abc.trycloudflare.com"})

    assert response.status_code == 404
