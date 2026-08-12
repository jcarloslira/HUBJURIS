"""Testes de Projetos: service multi-tenant, executor de ferramentas e loop agêntico."""

from collections.abc import AsyncIterator
from typing import Any

from app.agents.base import BaseAgent
from app.agents.ferramentas import montar_executor
from app.schemas.projetos import ProjetoCreate
from app.services.projetos import ProjetoService

# ── Fakes do Supabase (fila de resultados por tabela) ───────────


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


# ── Service ─────────────────────────────────────────────────────


async def test_criar_projeto_novo() -> None:
    db = _FakeDB({"condominios": [[], [{"id": "c1", "nome": "Ed. Aurora"}]]})
    svc = ProjetoService(db)  # type: ignore[arg-type]

    projeto, ja_existia = await svc.criar("e1", ProjetoCreate(nome="Ed. Aurora"))

    assert ja_existia is False
    assert projeto.id == "c1"
    assert projeto.nome == "Ed. Aurora"


async def test_criar_projeto_idempotente() -> None:
    db = _FakeDB({"condominios": [[{"id": "c1", "nome": "Ed. Aurora"}]]})
    svc = ProjetoService(db)  # type: ignore[arg-type]

    projeto, ja_existia = await svc.criar("e1", ProjetoCreate(nome="ed. aurora"))

    assert ja_existia is True  # mesmo nome (case-insensitive) não duplica
    assert projeto.id == "c1"


async def test_listar_conta_fatos_por_projeto() -> None:
    db = _FakeDB(
        {
            "condominios": [[{"id": "c1", "nome": "Ed. Aurora", "status": "ativo"}]],
            "condominio_fatos": [[{"condominio_id": "c1"}, {"condominio_id": "c1"}]],
        }
    )
    svc = ProjetoService(db)  # type: ignore[arg-type]

    projetos = await svc.listar("e1")

    assert len(projetos) == 1
    assert projetos[0].total_fatos == 2


# ── Executor das ferramentas ────────────────────────────────────


async def test_executor_criar_projeto_audita() -> None:
    db = _FakeDB({"condominios": [[], [{"id": "c1", "nome": "Ed. Aurora"}]]})
    svc = ProjetoService(db)  # type: ignore[arg-type]
    executar = montar_executor(svc, escritorio_id="e1", user_id="u1")

    saida = await executar("criar_projeto", {"nome": "Ed. Aurora"})

    assert "cadastrado" in saida.lower()
    assert "Ed. Aurora" in saida


async def test_executor_registrar_fato_com_autocriacao() -> None:
    db = _FakeDB(
        {
            "condominios": [
                [{"id": "c1", "nome": "Ed. Aurora"}],  # _buscar_por_nome (get-or-create)
                [{"id": "c1", "nome": "Ed. Aurora"}],  # _buscar_por_id (registrar_fato)
            ],
            "condominio_fatos": [[{"id": "f1", "fato": "Síndico é João", "origem": "agente"}]],
        }
    )
    svc = ProjetoService(db)  # type: ignore[arg-type]
    executar = montar_executor(svc, escritorio_id="e1", user_id="u1")

    saida = await executar("registrar_fato", {"projeto": "Ed. Aurora", "fato": "Síndico é João"})

    assert "Síndico é João" in saida


async def test_executor_detalhar_projeto_traz_memoria() -> None:
    db = _FakeDB(
        {
            "condominios": [
                [{"id": "c1", "nome": "Ed. Aurora", "status": "ativo"}],  # _buscar_por_nome
                [{"id": "c1", "nome": "Ed. Aurora"}],  # _buscar_por_id (listar_fatos)
            ],
            "condominio_fatos": [
                [{"id": "f1", "fato": "Síndico é o Sr. Pedro", "origem": "agente"}]
            ],
        }
    )
    svc = ProjetoService(db)  # type: ignore[arg-type]
    executar = montar_executor(svc, escritorio_id="e1", user_id="u1")

    saida = await executar("detalhar_projeto", {"nome": "Ed. Aurora"})

    assert "Ed. Aurora" in saida
    assert "Sr. Pedro" in saida  # recorda a memória do condomínio


async def test_executor_detalhar_projeto_inexistente() -> None:
    db = _FakeDB({"condominios": [[]]})  # _buscar_por_nome não acha
    svc = ProjetoService(db)  # type: ignore[arg-type]
    executar = montar_executor(svc, escritorio_id="e1", user_id="u1")

    saida = await executar("detalhar_projeto", {"nome": "Fantasma"})

    assert "não está cadastrado" in saida.lower()


async def test_executor_ferramenta_desconhecida() -> None:
    svc = ProjetoService(_FakeDB({}))  # type: ignore[arg-type]
    executar = montar_executor(svc, escritorio_id="e1", user_id=None)

    saida = await executar("apagar_tudo", {})

    assert "desconhecida" in saida.lower()


# ── Loop agêntico do BaseAgent ──────────────────────────────────


class _Usage:
    def __init__(self, entrada: int, saida: int) -> None:
        self.input_tokens = entrada
        self.output_tokens = saida


class _Bloco:
    def __init__(self, tipo: str, **kw: Any) -> None:
        self.type = tipo
        for chave, valor in kw.items():
            setattr(self, chave, valor)


class _FinalMsg:
    def __init__(self, content: list[_Bloco], stop_reason: str, usage: _Usage) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage


class _FakeStream:
    def __init__(self, textos: list[str], final: _FinalMsg) -> None:
        self._textos = textos
        self._final = final

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for t in self._textos:
                yield t

        return gen()

    async def get_final_message(self) -> _FinalMsg:
        return self._final


class _FakeMessages:
    def __init__(self, respostas: list[_FakeStream]) -> None:
        self._r = list(respostas)
        self.chamadas: list[dict[str, Any]] = []

    def stream(self, **kw: Any) -> _FakeStream:
        self.chamadas.append(kw)
        return self._r.pop(0)


class _FakeClient:
    def __init__(self, respostas: list[_FakeStream]) -> None:
        self.messages = _FakeMessages(respostas)


class _Agente(BaseAgent):
    system_prompt = "teste"


async def test_loop_executa_ferramenta_e_soma_tokens() -> None:
    passo1 = _FakeStream(
        ["Vou cadastrar. "],
        _FinalMsg(
            content=[
                _Bloco("text", text="Vou cadastrar. "),
                _Bloco("tool_use", name="criar_projeto", id="t1", input={"nome": "Ed X"}),
            ],
            stop_reason="tool_use",
            usage=_Usage(10, 5),
        ),
    )
    passo2 = _FakeStream(
        ["Pronto, cadastrei o Ed X."],
        _FinalMsg(
            content=[_Bloco("text", text="Pronto, cadastrei o Ed X.")],
            stop_reason="end_turn",
            usage=_Usage(8, 4),
        ),
    )
    client = _FakeClient([passo1, passo2])
    agente = _Agente(client)  # type: ignore[arg-type]

    chamadas: list[tuple[str, dict[str, Any]]] = []

    async def executar(nome: str, entrada: dict[str, Any]) -> str:
        chamadas.append((nome, entrada))
        return "Condomínio 'Ed X' cadastrado (id c9)."

    tokens: list[tuple[int, int]] = []

    async def on_usage(entrada: int, saida: int) -> None:
        tokens.append((entrada, saida))

    ferramentas = [{"name": "criar_projeto", "input_schema": {"type": "object", "properties": {}}}]
    texto = ""
    async for trecho in agente.responder_stream(
        [{"role": "user", "content": "cadastra o Ed X"}],
        on_usage=on_usage,
        ferramentas=ferramentas,
        executar_ferramenta=executar,
    ):
        texto += trecho

    assert chamadas == [("criar_projeto", {"nome": "Ed X"})]
    assert "Vou cadastrar." in texto and "Pronto, cadastrei o Ed X." in texto
    assert tokens == [(18, 9)]  # tokens somados entre as duas passadas
    # 2ª chamada ao modelo já inclui o tool_result no histórico
    assert len(client.messages.chamadas) == 2


async def test_loop_forca_resposta_final_ao_bater_o_teto() -> None:
    from app.agents.base import MAX_ITERACOES_FERRAMENTAS

    def tool_stream() -> _FakeStream:
        return _FakeStream(
            [""],
            _FinalMsg(
                content=[_Bloco("tool_use", name="buscar_no_drive", id="t", input={"termo": "x"})],
                stop_reason="tool_use",
                usage=_Usage(1, 1),
            ),
        )

    # todas as iterações pedem ferramenta → bate o teto sem nunca "terminar"
    respostas = [tool_stream() for _ in range(MAX_ITERACOES_FERRAMENTAS)]
    # a passada FORÇADA (sem ferramentas) entrega a resposta final
    respostas.append(
        _FakeStream(
            ["Segue o resultado com o que encontrei."],
            _FinalMsg(
                content=[_Bloco("text", text="ok")], stop_reason="end_turn", usage=_Usage(2, 3)
            ),
        )
    )
    client = _FakeClient(respostas)
    agente = _Agente(client)  # type: ignore[arg-type]

    async def executar(nome: str, entrada: dict[str, Any]) -> str:
        return "resultado da ferramenta"

    ferramentas = [
        {"name": "buscar_no_drive", "input_schema": {"type": "object", "properties": {}}}
    ]
    texto = ""
    async for trecho in agente.responder_stream(
        [{"role": "user", "content": "faz X"}],
        ferramentas=ferramentas,
        executar_ferramenta=executar,
    ):
        texto += trecho

    assert "Segue o resultado" in texto  # forçou a resposta final (não ficou "carregando e para")
    assert len(client.messages.chamadas) == MAX_ITERACOES_FERRAMENTAS + 1  # 5 + a de fechamento
    assert "tools" not in client.messages.chamadas[-1]  # a passada final é SEM ferramentas


async def test_sem_ferramentas_mantem_stream_simples() -> None:
    passo = _FakeStream(
        ["Olá!"],
        _FinalMsg(
            content=[_Bloco("text", text="Olá!")], stop_reason="end_turn", usage=_Usage(3, 2)
        ),
    )
    client = _FakeClient([passo])
    agente = _Agente(client)  # type: ignore[arg-type]

    texto = ""
    async for trecho in agente.responder_stream([{"role": "user", "content": "oi"}]):
        texto += trecho

    assert texto == "Olá!"
    assert len(client.messages.chamadas) == 1
    assert "tools" not in client.messages.chamadas[0]
