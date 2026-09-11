"""Ferramentas de gestão condominial — o Hub inteiro nas mãos do agente.

É o "MCP interno" do LexHub: o agente lê e escreve no nosso banco com o mesmo
alcance que o advogado tem na tela — painel do dia, diário de qualquer período,
ficha completa do condomínio, cadastro, anotações e a coleta do EasyJur/Tiflux.

Tudo escopado ao escritório do usuário logado e auditado pelo executor comum
(``acoes_agente``). Relatórios de período saem do diário gravado no Hub, em
milissegundos — as ferramentas do EasyJur/Tiflux ficam para o que o diário
não tem (texto integral de um andamento, partes, financeiro).
"""

import json
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

from app.agents.ferramentas_mcpai import data_iso
from app.services.gestao import TIPOS_EVENTO, GestaoError, GestaoService, hoje

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# Chars devolvidos ao modelo por chamada — o resumo sempre cabe; a lista é cortada.
_LIMITE = 18_000

_CAMPOS_CADASTRO = {
    "nome": "Nome do condomínio.",
    "cnpj": "CNPJ.",
    "endereco": "Endereço.",
    "cidade": "Cidade.",
    "uf": "UF (2 letras).",
    "sindico": "Síndico(a) atual, com contato se houver.",
    "administradora": "Administradora do condomínio.",
    "status": "ativo | inativo | encerrado.",
    "observacoes": "Observações de gestão.",
    "easyjur_cliente_id": "Id do cliente no EasyJur (para vincular manualmente).",
    "tiflux_cliente_id": "Id do cliente no Tiflux (para vincular manualmente).",
}

FERRAMENTAS_GESTAO: list[dict[str, Any]] = [
    {
        "name": "hub_painel",
        "description": (
            "O que aconteceu num DIA em todos os condomínios (processos novos, "
            "andamentos, encerramentos, tickets abertos/encerrados) + totais do "
            "escritório (processos ativos, valor em causa, tickets abertos). Use para "
            "'o que teve hoje/ontem', bom-dia do escritório e para abrir qualquer "
            "conversa de gestão. Sem data = hoje."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"dia": {"type": "string", "description": "AAAA-MM-DD ou DD/MM/AAAA."}},
        },
    },
    {
        "name": "hub_diario",
        "description": (
            "Diário do Hub num PERÍODO: todos os eventos gravados dia a dia (EasyJur e "
            "Tiflux), com resumo por tipo, por condomínio e valor dos processos novos. "
            "É a fonte PREFERIDA para relatórios de semana, mês ou ano — responde na "
            "hora, sem varrer APIs. Filtre por condomínio (nome), fonte ou tipo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_inicio": {"type": "string", "description": "AAAA-MM-DD ou DD/MM/AAAA."},
                "data_fim": {"type": "string", "description": "AAAA-MM-DD ou DD/MM/AAAA."},
                "condominio": {"type": "string", "description": "Nome (ou parte) do condomínio."},
                "fonte": {"type": "string", "enum": ["easyjur", "tiflux", "hub"]},
                "tipo": {"type": "string", "enum": list(TIPOS_EVENTO)},
            },
            "required": ["data_inicio", "data_fim"],
        },
    },
    {
        "name": "hub_condominios",
        "description": (
            "Lista os condomínios do escritório com a foto atual de cada um: processos "
            "ativos, valor em causa, tickets abertos, síndico, administradora e vínculos "
            "com EasyJur/Tiflux. Ordenado pelos que têm mais movimento."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"busca": {"type": "string", "description": "Filtro pelo nome."}},
        },
    },
    {
        "name": "hub_condominio",
        "description": (
            "Ficha completa de UM condomínio: cadastro, memória do escritório, evolução "
            "diária (processos ativos, valor, tickets) e os eventos mais recentes. Use "
            "SEMPRE antes de responder ou redigir algo sobre um condomínio específico."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"nome": {"type": "string", "description": "Nome como o usuário falou."}},
            "required": ["nome"],
        },
    },
    {
        "name": "hub_atualizar_condominio",
        "description": (
            "Atualiza o cadastro de um condomínio no Hub (síndico, administradora, CNPJ, "
            "endereço, status, observações, vínculo com EasyJur/Tiflux). Quando o usuário "
            "mencionar um desses dados de passagem, registre sem esperar pedido."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "condominio": {"type": "string", "description": "Nome atual do condomínio."},
                **{k: {"type": "string", "description": v} for k, v in _CAMPOS_CADASTRO.items()},
            },
            "required": ["condominio"],
        },
    },
    {
        "name": "hub_anotar",
        "description": (
            "Registra no diário do condomínio algo que não passa pelo EasyJur nem pelo "
            "Tiflux: reunião, assembleia, ligação do síndico, decisão do conselho, "
            "entrega de documento. Entra nos relatórios de período junto com o resto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "condominio": {"type": "string"},
                "titulo": {"type": "string", "description": "O que aconteceu, numa linha."},
                "descricao": {"type": "string"},
                "dia": {"type": "string", "description": "Data do fato (padrão: hoje)."},
            },
            "required": ["condominio", "titulo"],
        },
    },
    {
        "name": "hub_coletar",
        "description": (
            "Roda agora a coleta do EasyJur e do Tiflux e grava no diário os eventos "
            "novos e a foto do dia (leva ~1 minuto). A coleta já roda sozinha uma vez "
            "por dia; use quando o usuário quiser o dado deste minuto ou quando o painel "
            "disser que a última coleta não é de hoje."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


NOMES_GESTAO = {f["name"] for f in FERRAMENTAS_GESTAO}


# Dito ao agente quando o escritório logado não é o dono da conexão EasyJur/Tiflux.
# Sem isso ele "diagnosticava" conector desligado e mandava o usuário configurar
# algo que não existe na tela.
SEM_INTEGRACAO = (
    "Este escritório NÃO tem EasyJur nem Tiflux conectados ao Hub: a conexão deste "
    "servidor pertence a outro escritório e, por sigilo, os processos e tickets dele "
    "não aparecem aqui. Diga isso ao usuário com clareza. NÃO sugira 'Configurações → "
    "Conectores' (EasyJur e Tiflux não se conectam por lá) nem rodar hub_coletar: a "
    "ligação é feita pela equipe do LexHub. O que existe aqui são os condomínios "
    "cadastrados neste escritório e as anotações feitas no Hub."
)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _caber(obj: dict[str, Any], chave: str) -> str:
    """Corta itens do fim da lista até caber — nunca o texto no meio."""
    texto = _json(obj)
    lista = obj.get(chave)
    if len(texto) <= _LIMITE or not isinstance(lista, list):
        return texto
    baixo, alto = 0, len(lista)
    while baixo < alto:
        meio = (baixo + alto + 1) // 2
        if len(_json({**obj, chave: lista[:meio]})) <= _LIMITE - 400:
            baixo = meio
        else:
            alto = meio - 1
    aviso = (
        f"Mostrando {baixo} de {len(lista)} itens. Os totais e o resumo acima valem para "
        "TODOS; para ver o resto, estreite o período, o condomínio ou o tipo."
    )
    return _json({**obj, chave: lista[:baixo], "_aviso": aviso})


def _dia(valor: Any, padrao: date | None = None) -> date | None:
    iso = data_iso(valor)
    if iso is None:
        return padrao
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return padrao


def _enxuto(evento: dict[str, Any]) -> dict[str, Any]:
    linha = {
        "dia": evento.get("ocorrido_em"),
        "condominio": evento.get("condominio"),
        "tipo": TIPOS_EVENTO.get(evento.get("tipo", ""), evento.get("tipo")),
        "ref": evento.get("referencia"),
        "o_que": evento.get("titulo"),
    }
    if evento.get("valor"):
        linha["valor"] = evento["valor"]
    if evento.get("descricao"):
        linha["detalhe"] = str(evento["descricao"])[:240]
    return {k: v for k, v in linha.items() if v not in (None, "")}


def montar_handlers_gestao(gestao: GestaoService, escritorio_id: str) -> dict[str, Handler]:
    """Handlers das ferramentas de gestão, presos ao escritório do usuário."""

    async def condominio_por_nome(nome: Any) -> dict[str, Any]:
        return await gestao.buscar_condominio(escritorio_id, str(nome or ""))

    async def painel(entrada: dict[str, Any]) -> str:
        dia = _dia(entrada.get("dia"), hoje())
        dados = await gestao.painel(escritorio_id, dia)
        coleta = dados.get("ultima_coleta") or {}
        if not dados.get("integracao"):
            dados["aviso_integracao"] = SEM_INTEGRACAO
        elif coleta.get("dia") != hoje().isoformat() or coleta.get("status") != "ok":
            dados["aviso_coleta"] = (
                "A última coleta concluída não é de hoje — os números podem estar "
                "atrasados. Ofereça rodar hub_coletar."
            )
        dados["ultima_coleta"] = {
            k: coleta.get(k) for k in ("dia", "status", "concluida_em", "erro")
        }
        dados["eventos_do_dia"] = [_enxuto(e) for e in dados["eventos_do_dia"]]
        dados["destaques"] = [
            {k: c[k] for k in ("nome", "processos_ativos", "valor_causas_ativas",
                               "tickets_abertos")}
            for c in dados["destaques"]
        ]
        return _caber(dados, "eventos_do_dia")

    async def diario(entrada: dict[str, Any]) -> str:
        inicio = _dia(entrada.get("data_inicio"))
        fim = _dia(entrada.get("data_fim"))
        if inicio is None or fim is None:
            return "Informe data_inicio e data_fim (AAAA-MM-DD ou DD/MM/AAAA)."
        if fim < inicio:
            inicio, fim = fim, inicio
        integracao = await gestao.integracao_ativa(escritorio_id)
        condominio_id = None
        nome = None
        if entrada.get("condominio"):
            achado = await condominio_por_nome(entrada["condominio"])
            condominio_id, nome = str(achado["id"]), achado["nome"]
        dados = await gestao.eventos(
            escritorio_id,
            inicio=inicio,
            fim=fim,
            condominio_id=condominio_id,
            fonte=entrada.get("fonte") or None,
            tipo=entrada.get("tipo") or None,
        )
        saida: dict[str, Any] = {
            "periodo": dados["periodo"],
            "condominio": nome,
            "total_eventos": dados["total"],
            "resumo": dados["resumo"],
        }
        if not integracao:
            saida["aviso_integracao"] = SEM_INTEGRACAO
        if dados["cortado"]:
            saida["aviso"] = "Período grande demais: o total foi limitado. Divida o período."
        saida["eventos"] = [_enxuto(e) for e in dados["eventos"]]
        return _caber(saida, "eventos")

    async def condominios(entrada: dict[str, Any]) -> str:
        lista = await gestao.listar_condominios(escritorio_id, str(entrada.get("busca") or ""))
        itens = [{k: v for k, v in c.items() if v not in (None, "", 0) and k != "id"}
                 for c in lista]
        return _caber({"total": len(itens), "condominios": itens}, "condominios")

    async def condominio(entrada: dict[str, Any]) -> str:
        achado = await condominio_por_nome(entrada.get("nome"))
        ficha = await gestao.detalhe(escritorio_id, str(achado["id"]))
        cadastro = {
            k: v for k, v in ficha["condominio"].items()
            if v not in (None, "") and k not in ("escritorio_id", "drive_folder_id")
        }
        evolucao = ficha["evolucao"]
        variacao = None
        if len(evolucao) >= 2:
            primeiro, ultimo = evolucao[0], evolucao[-1]
            variacao = {"desde": primeiro["dia"]} | {
                campo: f"{primeiro[campo]} → {ultimo[campo]}"
                for campo in ("processos_ativos", "tickets_abertos")
            }
        saida = {
            "cadastro": cadastro,
            "foto_atual": evolucao[-1] if evolucao else None,
            "variacao": variacao,
            "memoria": [f["fato"] for f in ficha["memoria"]],
            "eventos_recentes": [
                _enxuto({**e, "condominio": None}) for e in ficha["eventos_recentes"]
            ],
        }
        return _caber(saida, "eventos_recentes")

    async def atualizar(entrada: dict[str, Any]) -> str:
        achado = await condominio_por_nome(entrada.get("condominio"))
        campos = {k: entrada[k] for k in _CAMPOS_CADASTRO if k in entrada}
        atualizado = await gestao.atualizar(escritorio_id, str(achado["id"]), campos)
        mudou = ", ".join(f"{k}: {atualizado.get(k)}" for k in campos)
        return f"Cadastro de '{atualizado.get('nome') or achado['nome']}' atualizado — {mudou}."

    async def anotar(entrada: dict[str, Any]) -> str:
        achado = await condominio_por_nome(entrada.get("condominio"))
        titulo = str(entrada.get("titulo") or "").strip()
        if len(titulo) < 3:
            return "Diga em uma linha o que aconteceu."
        evento = await gestao.registrar_evento(
            escritorio_id,
            str(achado["id"]),
            titulo=titulo,
            descricao=str(entrada.get("descricao") or ""),
            dia=_dia(entrada.get("dia"), hoje()),
        )
        return f"Anotado no diário de '{achado['nome']}' em {evento.get('ocorrido_em')}: {titulo}"

    async def coletar(_: dict[str, Any]) -> str:
        if not await gestao.integracao_ativa(escritorio_id):
            return SEM_INTEGRACAO
        resumo = await gestao.sincronizar(escritorio_id)
        resumo.pop("tickets_abertos_ids", None)
        return "Coleta concluída: " + _json(resumo)

    def protegido(handler: Handler) -> Handler:
        async def executar(entrada: dict[str, Any]) -> str:
            try:
                return await handler(entrada)
            except GestaoError as exc:
                return str(exc)

        return executar

    return {
        "hub_painel": protegido(painel),
        "hub_diario": protegido(diario),
        "hub_condominios": protegido(condominios),
        "hub_condominio": protegido(condominio),
        "hub_atualizar_condominio": protegido(atualizar),
        "hub_anotar": protegido(anotar),
        "hub_coletar": protegido(coletar),
    }


def periodo_padrao(dias: int = 7) -> tuple[date, date]:
    """Últimos ``dias`` até hoje — atalho para a UI."""
    fim = hoje()
    return fim - timedelta(days=dias - 1), fim
