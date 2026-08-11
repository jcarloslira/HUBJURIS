"""Ferramentas internas dos agentes — o "MCP interno" do LexHub.

São ações de baixo risco e reversíveis (cadastrar condomínio, registrar um fato
na memória, listar projetos) que os agentes executam diretamente no nosso banco,
sempre escopadas ao escritório do usuário logado e registradas na trilha de
auditoria (``acoes_agente``). Ações de efeito externo (Google Agenda, e-mail)
NÃO entram aqui — essas serão sempre propor-e-confirmar via conectores.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.projetos import ProjetoCreate
from app.services.projetos import ProjetoService

# Schemas das ferramentas expostas ao modelo (formato tool-use da Anthropic).
FERRAMENTAS_SISTEMA: list[dict[str, Any]] = [
    {
        "name": "criar_projeto",
        "description": (
            "Cadastra um condomínio (projeto) do escritório. Idempotente: se já "
            "existir um com o mesmo nome, retorna o existente sem duplicar. Use "
            "quando o usuário pedir para cadastrar/organizar um condomínio novo, "
            "ou quando você identificar um condomínio ainda não cadastrado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do condomínio."},
                "cnpj": {"type": "string", "description": "CNPJ, se conhecido."},
                "endereco": {"type": "string", "description": "Endereço, se conhecido."},
            },
            "required": ["nome"],
        },
    },
    {
        "name": "listar_projetos",
        "description": "Lista os condomínios (projetos) já cadastrados no escritório.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detalhar_projeto",
        "description": (
            "Recorda tudo que o Hub sabe sobre um condomínio: dados cadastrais e a "
            "MEMÓRIA (síndico, administradora, particularidades). Use ANTES de redigir "
            "uma peça para aquele condomínio, para aproveitar o contexto já registrado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string", "description": "Nome do condomínio."}},
            "required": ["nome"],
        },
    },
    {
        "name": "registrar_fato",
        "description": (
            "Salva um fato aprendido sobre um condomínio na memória do projeto "
            "(ex.: 'o síndico atual é o Sr. Pedro', 'o bloco A é gerido pela "
            "administradora X'). Se o condomínio ainda não existir, cadastra "
            "automaticamente antes de salvar o fato."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "projeto": {"type": "string", "description": "Nome do condomínio."},
                "fato": {"type": "string", "description": "O fato a memorizar."},
            },
            "required": ["projeto", "fato"],
        },
    },
]

# Subconjunto de LEITURA do Hub — dado TAMBÉM aos especialistas para recordarem o
# contexto de um condomínio antes de produzir a peça.
_NOMES_HUB_LEITURA = {"listar_projetos", "detalhar_projeto"}
FERRAMENTAS_HUB_LEITURA: list[dict[str, Any]] = [
    f for f in FERRAMENTAS_SISTEMA if f["name"] in _NOMES_HUB_LEITURA
]

Executor = Callable[[str, dict[str, Any]], Awaitable[str]]


def montar_executor(
    projetos: ProjetoService,
    *,
    escritorio_id: str,
    user_id: str | None,
    agente: str = "supervisor",
    extra_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] | None = None,
) -> Executor:
    """Cria o executor das ferramentas, vinculado a um escritório e usuário.

    O executor nunca levanta exceção para o modelo: qualquer falha vira uma
    string de resultado amigável, para não derrubar o streaming da resposta.
    Toda ação bem-sucedida é gravada na trilha de auditoria.
    """

    async def _auditar(ferramenta: str, argumentos: dict[str, Any], resultado: str) -> None:
        try:
            await projetos.registrar_acao(
                escritorio_id=escritorio_id,
                user_id=user_id,
                agente=agente,
                ferramenta=ferramenta,
                argumentos=argumentos,
                resultado=resultado,
            )
        except Exception:  # noqa: BLE001 - auditoria não pode derrubar a ação
            pass

    async def _criar_projeto(entrada: dict[str, Any]) -> str:
        nome = str(entrada.get("nome") or "").strip()
        if len(nome) < 2:
            return "Não consegui cadastrar: informe o nome do condomínio."
        payload = ProjetoCreate(
            nome=nome,
            cnpj=(entrada.get("cnpj") or None),
            endereco=(entrada.get("endereco") or None),
        )
        projeto, ja_existia = await projetos.criar(escritorio_id, payload)
        if ja_existia:
            return f"O condomínio '{projeto.nome}' já estava cadastrado (id {projeto.id})."
        return f"Condomínio '{projeto.nome}' cadastrado com sucesso (id {projeto.id})."

    async def _listar_projetos(_: dict[str, Any]) -> str:
        itens = await projetos.listar(escritorio_id)
        if not itens:
            return "Nenhum condomínio cadastrado ainda neste escritório."
        linhas = [f"- {p.nome} ({p.total_fatos} fato(s) na memória)" for p in itens]
        return "Condomínios cadastrados:\n" + "\n".join(linhas)

    async def _detalhar_projeto(entrada: dict[str, Any]) -> str:
        nome = str(entrada.get("nome") or "").strip()
        if len(nome) < 2:
            return "Informe o nome do condomínio a detalhar."
        projeto, fatos = await projetos.detalhar_por_nome(escritorio_id, nome)
        if projeto is None:
            return f"O condomínio '{nome}' ainda não está cadastrado no Hub."
        linhas = [f"Condomínio: {projeto.nome} (status: {projeto.status})"]
        if projeto.cnpj:
            linhas.append(f"CNPJ: {projeto.cnpj}")
        if projeto.endereco:
            linhas.append(f"Endereço: {projeto.endereco}")
        if fatos:
            linhas.append("Memória do condomínio:")
            linhas.extend(f"- {f.fato}" for f in fatos)
        else:
            linhas.append("Sem fatos registrados na memória ainda.")
        return "\n".join(linhas)

    async def _registrar_fato(entrada: dict[str, Any]) -> str:
        nome = str(entrada.get("projeto") or "").strip()
        fato = str(entrada.get("fato") or "").strip()
        if len(nome) < 2 or len(fato) < 3:
            return "Preciso do nome do condomínio e do fato a memorizar."
        projeto, _ = await projetos.criar(escritorio_id, ProjetoCreate(nome=nome))
        salvo = await projetos.registrar_fato(escritorio_id, projeto.id, fato, origem="agente")
        return f"Anotado na memória de '{projeto.nome}': {salvo.fato}"

    handlers: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
        "criar_projeto": _criar_projeto,
        "listar_projetos": _listar_projetos,
        "detalhar_projeto": _detalhar_projeto,
        "registrar_fato": _registrar_fato,
    }
    if extra_handlers:
        handlers.update(extra_handlers)

    async def executar(nome: str, entrada: dict[str, Any]) -> str:
        handler = handlers.get(nome)
        if handler is None:
            return f"Ferramenta desconhecida: {nome}"
        try:
            resultado = await handler(entrada)
        except Exception as exc:  # noqa: BLE001 - falha vira resultado, não crash
            return f"Não foi possível concluir '{nome}': {exc}"
        await _auditar(nome, entrada, resultado)
        return resultado

    return executar
