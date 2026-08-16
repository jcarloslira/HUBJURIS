"""Ferramentas dos agentes sobre o mcp.ai ("Banco MCP"): EasyJur e Tiflux.

Conjunto CURADO (não os 71 endpoints): consultas ao sistema jurídico (EasyJur —
processos, partes, movimentações, financeiro, clientes, agenda) e ao helpdesk
(Tiflux — tickets). LEITURA é autônoma; ESCRITA (abrir/responder ticket) é
propor-e-confirmar. Escopo atual: a workspace do mcp.ai configurada (conta do
escritório). Novos endpoints entram só acrescentando uma linha em ``_CATALOGO``.
"""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.mcpai import MCPAIClient, MCPAIError

# Chars devolvidos ao modelo. Uma página cheia (20 processos) dá ~8k; a folga
# garante que nenhuma página perca a cauda por causa de um registro mais gordo.
_LIMITE_RESULTADO = 12_000
# Alguns andamentos trazem log de acordo com ~3.000 chars. Sem um teto por campo,
# UM registro gordo estoura o orçamento e derruba a cauda da página inteira —
# some processo do relatório sem ninguém perceber. O que importa do andamento
# (data + o que aconteceu) está sempre no começo.
_LIMITE_ANDAMENTO = 400

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# Campos que valem a pena de cada PROCESSO do EasyJur (a API devolve ~80 por item,
# a maioria ruído; sem enxugar, só 2 processos cabem no orçamento de contexto).
_CAMPOS_PROCESSO = (
    "id_processo",
    "numero",
    "titulo_acao",
    "nome_contrario",
    "vinculo",
    "area_info",
    "status_label",
    "instancia_label",
    "valor_causa",
    "vara",
    "comarca",
    "uf",
    "fase_atual",
    "data_distribuicao",
    "ultimo_andamento",
)
# Campos úteis de cada PESSOA/cliente (dropa campos_personalizados e ruído).
_CAMPOS_PESSOA = (
    "id",
    "nome",
    "apelido",
    "fisica_juridica",
    "cpf",
    "cnpj",
    "email",
    "celular",
)


def _limpar_html(valor: Any) -> Any:
    """Remove tags e desescapa entidades HTML de um texto (ex.: último andamento)."""
    if not isinstance(valor, str):
        return valor
    texto = re.sub(r"<[^>]+>", " ", valor)
    for ent, char in (("&nbsp;", " "), ("&ccedil;", "ç"), ("&atilde;", "ã"),
                      ("&aacute;", "á"), ("&eacute;", "é"), ("&iacute;", "í"),
                      ("&oacute;", "ó"), ("&uacute;", "ú"), ("&ecirc;", "ê"),
                      ("&ocirc;", "ô"), ("&atilde", "ã"), ("&amp;", "&")):
        texto = texto.replace(ent, char)
    return re.sub(r"\s+", " ", texto).strip()


def _enxugar(path: str, resultado: Any) -> Any:
    """Enxuga a resposta do EasyJur/Tiflux: remove ``raw_data`` (duplica tudo) e,
    em listagens de processos/pessoas, projeta cada item nos campos essenciais e
    preserva ``meta`` (total, total_pages) para o agente saber quando paginar."""
    if not isinstance(resultado, dict):
        return resultado
    resultado = {k: v for k, v in resultado.items() if k != "raw_data"}
    itens = resultado.get("data")
    if isinstance(itens, list) and itens and isinstance(itens[0], dict):
        if "processos" in path:
            campos = _CAMPOS_PROCESSO
        elif "pessoas" in path:
            campos = _CAMPOS_PESSOA
        else:
            campos = ()
        if campos:
            enxutos = []
            for item in itens:
                linha = {c: item.get(c) for c in campos if item.get(c) not in (None, "", 0)}
                if "ultimo_andamento" in linha:
                    andamento = _limpar_html(linha["ultimo_andamento"])
                    if len(andamento) > _LIMITE_ANDAMENTO:
                        andamento = andamento[:_LIMITE_ANDAMENTO] + " […]"
                    linha["ultimo_andamento"] = andamento
                enxutos.append(linha)
            resultado["data"] = enxutos
    return resultado

# name -> (path, escrita, descrição, propriedades, obrigatórios)
_CATALOGO: list[dict[str, Any]] = [
    # ── EasyJur — jurídico (somente leitura) ──────────────────────
    {
        "name": "easyjur_processos",
        "path": "/api/easyjur/list/processos",
        "escrita": False,
        "descricao": (
            "Lista processos do EasyJur (paginado, 20 por página — o escritório tem MILHARES; "
            "um único condomínio pode ter dezenas). Para achar os processos de um condomínio, "
            "PRIMEIRO use easyjur_clientes(nome=...) para pegar o id do cliente e depois passe "
            "'id_cliente' aqui. O campo 'meta.total' e 'meta.total_pages' dizem QUANTOS existem "
            "no total — se houver mais de uma página, chame de novo com 'page'=2, 3… até cobrir "
            "todas ANTES de concluir. Nunca afirme um total sem ter percorrido todas as páginas."
        ),
        "props": {
            "id_cliente": {
                "type": "integer",
                "description": "Filtra os processos deste cliente (id de easyjur_clientes).",
            },
            # ATENÇÃO: a API ignora em silêncio qualquer outro nome (ex.: "pagina") e
            # devolve sempre a página 1 — o que faz o agente concluir que não há mais nada.
            "page": {"type": "integer", "description": "Página (20 por página; padrão 1)."},
        },
        "obrig": [],
    },
    {
        "name": "easyjur_processo",
        "path": "/api/easyjur/get/processo",
        "escrita": False,
        "descricao": "Detalha um processo do EasyJur pelo seu id.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_partes",
        "path": "/api/easyjur/processo/partes",
        "escrita": False,
        "descricao": "Partes (autor, réu, terceiros) de um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_movimentacoes",
        "path": "/api/easyjur/processo/mensagens",
        "escrita": False,
        "descricao": "Movimentações/andamentos e mensagens de um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_financeiro",
        "path": "/api/easyjur/processo/financeiros",
        "escrita": False,
        "descricao": "Lançamentos financeiros vinculados a um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_clientes",
        "path": "/api/easyjur/list/pessoas",
        "escrita": False,
        "descricao": (
            "Busca pessoas/clientes no EasyJur (condomínios, síndicos, contrários). Passe 'nome' "
            "para FILTRAR por nome (ex.: 'Casablanca') — sem filtro vem só a 1ª página. "
            "Retorna o id do cliente, que você usa em easyjur_processos(id_cliente=...)."
        ),
        "props": {
            "nome": {
                "type": "string",
                "description": "Filtra clientes cujo nome contém este texto (ex.: 'Casablanca').",
            }
        },
        "obrig": [],
    },
    {
        "name": "easyjur_cliente",
        "path": "/api/easyjur/get/pessoa",
        "escrita": False,
        "descricao": "Detalha uma pessoa/cliente do EasyJur pelo id.",
        "props": {"pessoa_id": {"type": "integer", "description": "id da pessoa."}},
        "obrig": ["pessoa_id"],
    },
    {
        "name": "easyjur_agenda",
        "path": "/api/easyjur/list/agenda",
        "escrita": False,
        "descricao": "Lista compromissos/prazos da agenda do EasyJur.",
        "props": {},
        "obrig": [],
    },
    # ── Tiflux — helpdesk (leitura) ───────────────────────────────
    {
        "name": "tiflux_tickets",
        "path": "/api/tiflux/list/tickets",
        "escrita": False,
        "descricao": "Lista os tickets/chamados do Tiflux (número, cliente, status, mesa).",
        "props": {},
        "obrig": [],
    },
    {
        "name": "tiflux_ticket_respostas",
        "path": "/api/tiflux/list/ticket/answers",
        "escrita": False,
        "descricao": "Respostas/histórico de um ticket do Tiflux.",
        "props": {"ticket_number": {"type": "integer", "description": "número do ticket."}},
        "obrig": ["ticket_number"],
    },
    # ── Tiflux — helpdesk (escrita: propor-e-confirmar) ───────────
    {
        "name": "tiflux_criar_ticket",
        "path": "/api/tiflux/create/ticket",
        "escrita": True,
        "descricao": (
            "Abre um ticket/chamado no Tiflux. AÇÃO EXTERNA: proponha e peça confirmação "
            "ao usuário ANTES de chamar."
        ),
        "props": {
            "title": {"type": "string", "description": "Título do chamado."},
            "description": {"type": "string", "description": "Descrição do chamado."},
        },
        "obrig": ["title", "description"],
    },
    {
        "name": "tiflux_responder_ticket",
        "path": "/api/tiflux/create/ticket/answer",
        "escrita": True,
        "descricao": (
            "Responde um ticket do Tiflux. AÇÃO EXTERNA: proponha e peça confirmação antes."
        ),
        "props": {
            "ticket_number": {"type": "integer", "description": "número do ticket."},
            "text": {"type": "string", "description": "Texto da resposta."},
        },
        "obrig": ["ticket_number", "text"],
    },
]

# Schemas expostos ao modelo (formato tool-use da Anthropic).
FERRAMENTAS_MCPAI: list[dict[str, Any]] = [
    {
        "name": t["name"],
        "description": t["descricao"],
        "input_schema": {
            "type": "object",
            "properties": t["props"],
            "required": t["obrig"],
        },
    }
    for t in _CATALOGO
]

NOMES_MCPAI = {t["name"] for t in _CATALOGO}
_ROTA: dict[str, str] = {t["name"]: t["path"] for t in _CATALOGO}


def _sistema(nome: str) -> str:
    return "EasyJur" if nome.startswith("easyjur") else "Tiflux"


def montar_handlers_mcpai(client: MCPAIClient) -> dict[str, Handler]:
    """Handlers das ferramentas mcp.ai, ligados ao cliente REST configurado."""

    def _fazer(path: str, nome: str) -> Handler:
        async def handler(entrada: dict[str, Any]) -> str:
            try:
                resultado = await client.chamar(path, entrada)
            except MCPAIError as exc:
                return f"Não consegui consultar o {_sistema(nome)} agora ({exc})."
            texto = json.dumps(_enxugar(path, resultado), ensure_ascii=False)
            if len(texto) > _LIMITE_RESULTADO:
                texto = texto[:_LIMITE_RESULTADO] + " …[truncado — use 'page' p/ ver mais]"
            return texto

        return handler

    return {t["name"]: _fazer(t["path"], t["name"]) for t in _CATALOGO}
