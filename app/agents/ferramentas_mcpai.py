"""Ferramentas dos agentes sobre o mcp.ai ("Banco MCP"): EasyJur e Tiflux.

Conjunto CURADO (não os 71 endpoints): consultas ao sistema jurídico (EasyJur —
processos, partes, movimentações, financeiro, clientes, agenda) e ao helpdesk
(Tiflux — tickets). LEITURA é autônoma; ESCRITA (abrir/responder ticket) é
propor-e-confirmar. Escopo atual: a workspace do mcp.ai configurada (conta do
escritório). Novos endpoints entram só acrescentando uma linha em ``_CATALOGO``.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.mcpai import MCPAIClient, MCPAIError

_LIMITE_RESULTADO = 3200  # chars devolvidos ao modelo (evita estourar contexto)

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# name -> (path, escrita, descrição, propriedades, obrigatórios)
_CATALOGO: list[dict[str, Any]] = [
    # ── EasyJur — jurídico (somente leitura) ──────────────────────
    {
        "name": "easyjur_processos",
        "path": "/api/easyjur/list/processos",
        "escrita": False,
        "descricao": (
            "Lista processos do EasyJur (paginado, 20 por página — o escritório tem MILHARES). "
            "Para achar os processos de um condomínio, PRIMEIRO use easyjur_clientes(nome=...) "
            "para pegar o id do cliente e depois passe 'id_cliente' aqui. Use 'pagina' para "
            "avançar."
        ),
        "props": {
            "id_cliente": {
                "type": "integer",
                "description": "Filtra os processos deste cliente (id de easyjur_clientes).",
            },
            "pagina": {"type": "integer", "description": "Página (20 por página; padrão 1)."},
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
            texto = json.dumps(resultado, ensure_ascii=False)
            if len(texto) > _LIMITE_RESULTADO:
                texto = texto[:_LIMITE_RESULTADO] + " …[resultado truncado]"
            return texto

        return handler

    return {t["name"]: _fazer(t["path"], t["name"]) for t in _CATALOGO}
