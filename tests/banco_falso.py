"""Supabase em memória para testar services sem banco (select/insert/upsert/update)."""

import uuid
from types import SimpleNamespace
from typing import Any


class _Consulta:
    def __init__(self, banco: "BancoFalso", tabela: str) -> None:
        self._banco = banco
        self._tabela = tabela
        self._filtros: list[tuple[str, str, Any]] = []
        self._ordem: list[tuple[str, bool]] = []
        self._fatia: tuple[int, int] | None = None
        self._limite: int | None = None
        self._acao = "select"
        self._dados: Any = None
        self._conflito: list[str] = []
        self._ignorar = False

    def select(self, *_: Any, **__: Any) -> "_Consulta":
        return self

    def eq(self, coluna: str, valor: Any) -> "_Consulta":
        self._filtros.append((coluna, "eq", valor))
        return self

    def gte(self, coluna: str, valor: Any) -> "_Consulta":
        self._filtros.append((coluna, "gte", valor))
        return self

    def lte(self, coluna: str, valor: Any) -> "_Consulta":
        self._filtros.append((coluna, "lte", valor))
        return self

    def order(self, coluna: str, desc: bool = False) -> "_Consulta":
        self._ordem.append((coluna, desc))
        return self

    def limit(self, n: int) -> "_Consulta":
        self._limite = n
        return self

    def range(self, inicio: int, fim: int) -> "_Consulta":
        self._fatia = (inicio, fim)
        return self

    def insert(self, dados: Any) -> "_Consulta":
        self._acao, self._dados = "insert", dados
        return self

    def upsert(
        self, dados: Any, on_conflict: str = "id", ignore_duplicates: bool = False
    ) -> "_Consulta":
        self._acao, self._dados = "upsert", dados
        self._conflito = [c.strip() for c in on_conflict.split(",")]
        self._ignorar = ignore_duplicates
        return self

    def update(self, dados: dict[str, Any]) -> "_Consulta":
        self._acao, self._dados = "update", dados
        return self

    def _casa(self, linha: dict[str, Any]) -> bool:
        for coluna, op, valor in self._filtros:
            atual = linha.get(coluna)
            if op == "eq" and str(atual) != str(valor):
                return False
            if op == "gte" and (atual is None or str(atual) < str(valor)):
                return False
            if op == "lte" and (atual is None or str(atual) > str(valor)):
                return False
        return True

    async def execute(self) -> SimpleNamespace:
        linhas = self._banco.tabelas.setdefault(self._tabela, [])
        if self._acao in ("insert", "upsert"):
            novas = self._dados if isinstance(self._dados, list) else [self._dados]
            gravadas = []
            for nova in novas:
                nova = dict(nova)
                if self._acao == "upsert":
                    existente = next(
                        (
                            linha for linha in linhas
                            if all(str(linha.get(c)) == str(nova.get(c)) for c in self._conflito)
                        ),
                        None,
                    )
                    if existente is not None:
                        if not self._ignorar:
                            existente.update(nova)
                            gravadas.append(existente)
                        continue
                nova.setdefault("id", str(uuid.uuid4()))
                nova.setdefault("status", "ativo" if self._tabela == "condominios" else "rodando")
                nova.setdefault("iniciada_em", "2026-09-11T10:00:00+00:00")
                linhas.append(nova)
                gravadas.append(nova)
            return SimpleNamespace(data=gravadas)
        alvo = [linha for linha in linhas if self._casa(linha)]
        if self._acao == "update":
            for linha in alvo:
                linha.update(self._dados)
            return SimpleNamespace(data=alvo)
        for coluna, desc in reversed(self._ordem):
            alvo.sort(key=lambda linha: str(linha.get(coluna) or ""), reverse=desc)
        if self._fatia:
            alvo = alvo[self._fatia[0] : self._fatia[1] + 1]
        if self._limite is not None:
            alvo = alvo[: self._limite]
        return SimpleNamespace(data=[dict(linha) for linha in alvo])


class BancoFalso:
    """Imita o ``AsyncClient`` do supabase-py no que os services usam."""

    def __init__(self) -> None:
        self.tabelas: dict[str, list[dict[str, Any]]] = {}

    def table(self, nome: str) -> _Consulta:
        return _Consulta(self, nome)
