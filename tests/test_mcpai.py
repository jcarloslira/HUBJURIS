"""Testes do conector mcp.ai (EasyJur/Tiflux): cliente e ferramentas dos agentes."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.agents.ferramentas_mcpai import (
    FERRAMENTAS_MCPAI,
    NOMES_MCPAI,
    montar_handlers_mcpai,
)
from app.services.mcpai import MCPAIClient, MCPAIError


class _Settings:
    MCP_AI_API_KEY = "sk_live_x"
    MCP_AI_BASE_URL = "https://api.mcp.ai"


class _SettingsVazio(_Settings):
    MCP_AI_API_KEY = ""


def test_ativo_depende_da_key() -> None:
    assert MCPAIClient(AsyncMock(), _Settings()).ativo is True
    assert MCPAIClient(AsyncMock(), _SettingsVazio()).ativo is False


def test_schemas_e_nomes_batem() -> None:
    nomes = {f["name"] for f in FERRAMENTAS_MCPAI}
    assert nomes == NOMES_MCPAI
    assert "easyjur_processos" in nomes and "tiflux_criar_ticket" in nomes


def test_paginacao_de_processos_usa_page() -> None:
    """A API do EasyJur ignora em silêncio qualquer outro nome (ex.: 'pagina') e
    devolve sempre a página 1 — o agente conclui que não há mais nada e erra o total."""
    processos = next(f for f in FERRAMENTAS_MCPAI if f["name"] == "easyjur_processos")
    props = processos["input_schema"]["properties"]
    assert "page" in props, "o parâmetro de paginação precisa se chamar 'page'"
    assert "pagina" not in props


@pytest.mark.asyncio
async def test_handler_leitura_chama_rota_certa() -> None:
    client = AsyncMock()
    client.chamar.return_value = {
        "data": [{"numero": "123", "nome_contrario": "FULANO", "campo_ruido": "x" * 500}],
        "meta": {"total": 42, "total_pages": 3},
        "raw_data": "x" * 9000,  # a API duplica tudo aqui — deve ser removido
    }
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["easyjur_processos"]({})

    client.chamar.assert_awaited_once_with("/api/easyjur/list/processos", {})
    assert "123" in saida and "FULANO" in saida  # campos essenciais mantidos
    assert "campo_ruido" not in saida  # ruído do processo é enxugado
    assert "raw_data" not in saida  # duplicata gigante removida
    assert json.loads(saida)["meta"] == {"total": 42, "total_pages": 3}  # p/ saber quanto falta


@pytest.mark.asyncio
async def test_handler_escrita_repassa_args() -> None:
    client = AsyncMock()
    client.chamar.return_value = {"ticket_number": 999}
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["tiflux_criar_ticket"](
        {"title": "Vazamento", "description": "Apto 42"}
    )

    path, args = client.chamar.call_args.args
    assert path == "/api/tiflux/create/ticket"
    assert args["title"] == "Vazamento"
    assert "999" in saida


@pytest.mark.asyncio
async def test_handler_erro_vira_mensagem_amigavel() -> None:
    client = AsyncMock()
    client.chamar.side_effect = MCPAIError("boom")
    handlers = montar_handlers_mcpai(client)

    saida = await handlers["tiflux_tickets"]({})

    assert "Tiflux" in saida and "boom" in saida


def test_tickets_do_tiflux_sao_enxugados() -> None:
    """O Tiflux devolve a lista em 'value' (não 'data') com 21 campos por ticket:
    sem tratar esse formato, uma página estoura o orçamento e some com metade."""
    from app.agents.ferramentas_mcpai import _enxugar

    bruto = {
        "value": [
            {
                "ticket_number": 6331,
                "title": "Proposta eletro posto",
                "client": {"id": 1889559, "name": "COND. SQB"},
                "responsible": {"id": 1008331, "name": "Pedro Martinez"},
                "created_by_id": 1026775,
                "followers": "",
                "reopen_count": 0,
                "is_revised": False,
            }
        ],
        "total_items": 156,
        "raw_data": "x" * 9000,
    }

    enxuto = _enxugar("/api/tiflux/list/tickets", bruto)
    ticket = enxuto["value"][0]

    assert enxuto["total_items"] == 156  # o total real precisa sobreviver
    assert "raw_data" not in enxuto
    assert ticket["client"] == "COND. SQB"  # {id, name} vira só o nome
    assert ticket["responsible"] == "Pedro Martinez"
    assert "created_by_id" not in ticket  # ruído fora
    assert "reopen_count" not in ticket


# ── Limites reais das APIs e varreduras no servidor ────────────────


class _ClienteFalso:
    """Imita o MCPAIClient: registra as chamadas e responde por página."""

    def __init__(self, responder: Any) -> None:
        self.chamadas: list[tuple[str, dict[str, Any]]] = []
        self._responder = responder

    async def chamar(self, path: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(args or {})
        self.chamadas.append((path, args))
        return self._responder(path, args)


@pytest.mark.asyncio
async def test_page_size_do_easyjur_nunca_passa_de_100() -> None:
    """Acima de 100 o EasyJur responde 422 e a consulta INTEIRA falha — foi assim
    que o page_size=200 recomendado ao agente quebrou as varreduras em produção."""
    client = _ClienteFalso(lambda p, a: {"data": [], "meta": {"total": 0, "total_pages": 1}})
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    await handlers["easyjur_processos"]({"page_size": 200})
    await handlers["easyjur_clientes"]({"nome": "x", "page_size": 500})

    assert client.chamadas[0][1]["page_size"] == 100
    assert client.chamadas[1][1]["page_size"] == 100


@pytest.mark.asyncio
async def test_limites_do_tiflux_sao_aplicados() -> None:
    client = _ClienteFalso(lambda p, a: {"value": [], "total_items": 0})
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    await handlers["tiflux_tickets"]({"limit": 1000, "offset": 0, "client_ids": 1889559})

    args = client.chamadas[0][1]
    assert args["limit"] == 200  # a API corta em 200 de qualquer jeito
    assert args["offset"] == 1  # offset é número da página, começa em 1
    assert args["client_ids"] == ["1889559"]


def test_resposta_grande_corta_itens_e_nao_o_json() -> None:
    """Cortar o texto no meio entregava JSON quebrado e o agente achava que tinha
    visto tudo; agora corta itens inteiros e avisa quantos ficaram de fora."""
    from app.agents.ferramentas_mcpai import _LIMITE_RESULTADO, _serializar

    itens = [{"numero": str(i), "x": "y" * 300} for i in range(200)]
    texto = _serializar({"meta": {"total": 999}, "data": itens})
    corpo = json.loads(texto)  # continua sendo JSON válido

    assert len(texto) <= _LIMITE_RESULTADO
    assert 0 < len(corpo["data"]) < 200
    assert "de 200 itens" in corpo["_aviso"]
    assert corpo["meta"] == {"total": 999}  # o total real sobrevive ao corte


def _paginas_easyjur(processos: list[dict[str, Any]]) -> Any:
    def responder(path: str, args: dict[str, Any]) -> dict[str, Any]:
        pagina, tamanho = args.get("page", 1), args.get("page_size", 20)
        fatia = processos[(pagina - 1) * tamanho : pagina * tamanho]
        total_paginas = max(1, -(-len(processos) // tamanho))
        return {"data": fatia, "meta": {"total": len(processos), "total_pages": total_paginas}}

    return responder


@pytest.mark.asyncio
async def test_periodo_varre_todas_as_paginas_e_filtra_pela_data() -> None:
    processos = [
        {
            "id_processo": i,
            "numero": f"P{i}",
            "data_distribuicao": f"2026-0{7 + (i % 3)}-15",  # julho, agosto, setembro
            "valor_causa": 100.0,
            "uf": "GO" if i % 2 else "DF",
            "cliente_info": {"id": 1, "nome": "COND. VILA PARK"},
        }
        for i in range(250)
    ]
    client = _ClienteFalso(_paginas_easyjur(processos))
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    saida = json.loads(
        await handlers["easyjur_processos_por_periodo"](
            {"data_inicio": "01/08/2026", "data_fim": "2026-08-31"}  # aceita os dois formatos
        )
    )

    assert sorted(a["page"] for _, a in client.chamadas) == [1, 2, 3]  # 250 / 100
    assert all(a["page_size"] == 100 for _, a in client.chamadas)
    esperados = sum(1 for p in processos if p["data_distribuicao"].startswith("2026-08"))
    resumo = saida["resumo"]
    assert resumo["encontrados"] == esperados
    assert resumo["processos_varridos"] == 250
    assert resumo["valor_total_das_causas"] == esperados * 100.0
    assert all(p["data_distribuicao"].startswith("2026-08") for p in saida["data"])
    assert saida["data"][0]["cliente"] == "COND. VILA PARK"  # cliente legível na lista


@pytest.mark.asyncio
async def test_periodo_continua_a_lista_sem_perder_nem_repetir_item() -> None:
    """Com página de tamanho fixo, os itens que não cabiam sumiam entre uma página e a
    seguinte (em produção: 34 de 42). Agora cada resposta leva o que cabe, diz de onde
    continuar, e a continuação sai do cache do turno sem varrer de novo."""
    processos = [
        {
            "id_processo": i,
            "data_distribuicao": "2026-08-10",
            "nome_contrario": "PARTE CONTRÁRIA COM NOME BEM COMPRIDO " * 3,
            "ultimo_andamento": "Andamento longo do processo " * 20,
        }
        for i in range(120)
    ]
    client = _ClienteFalso(_paginas_easyjur(processos))
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]
    args: dict[str, Any] = {"data_inicio": "2026-08-01", "data_fim": "2026-08-31"}

    vistos: list[int] = []
    respostas = 0
    chamadas_da_varredura = None
    while True:
        saida = json.loads(await handlers["easyjur_processos_por_periodo"](args))
        respostas += 1
        chamadas_da_varredura = chamadas_da_varredura or len(client.chamadas)
        assert "_aviso" not in saida  # nada foi cortado às escondidas
        vistos.extend(p["id_processo"] for p in saida["data"])
        proxima = saida["resumo"].get("proxima")
        if not proxima:
            break
        args["a_partir_de"] = int(proxima.split("a_partir_de=")[1].split()[0])

    assert respostas > 1  # a lista de fato não coube numa resposta só
    assert sorted(vistos) == list(range(120))  # todos, nenhum repetido
    assert len(client.chamadas) == chamadas_da_varredura  # continuações vieram do cache


def test_comarca_vem_pelo_nome_e_nao_pelo_codigo() -> None:
    from app.agents.ferramentas_mcpai import _enxugar_processo

    linha = _enxugar_processo(
        {"numero": "1", "comarca": "5599", "comarca_info": {"id": 5599, "nome": "Guará"}}
    )

    assert linha["comarca"] == "Guará"


@pytest.mark.asyncio
async def test_periodo_avisa_quando_uma_pagina_falha() -> None:
    """Resultado parcial tem de chegar como parcial, não como a verdade."""
    responder = _paginas_easyjur(
        [{"id_processo": i, "data_distribuicao": "2026-08-10"} for i in range(250)]
    )

    def instavel(path: str, args: dict[str, Any]) -> dict[str, Any]:
        if args.get("page") == 2:
            raise MCPAIError("timeout")
        return responder(path, args)

    handlers = montar_handlers_mcpai(_ClienteFalso(instavel))  # type: ignore[arg-type]

    saida = json.loads(
        await handlers["easyjur_processos_por_periodo"](
            {"data_inicio": "2026-08-01", "data_fim": "2026-08-31"}
        )
    )

    assert saida["resumo"]["encontrados"] == 150  # páginas 1 e 3
    assert "falharam" in saida["resumo"]["aviso"]


@pytest.mark.asyncio
async def test_periodo_sem_datas_pede_as_datas() -> None:
    handlers = montar_handlers_mcpai(_ClienteFalso(lambda p, a: {}))  # type: ignore[arg-type]

    saida = await handlers["easyjur_processos_por_periodo"]({"data_inicio": "agosto"})

    assert "data_inicio" in saida and "data_fim" in saida


def _paginas_tiflux(total: int) -> Any:
    tickets = [
        {
            "ticket_number": 1000 + i,
            "title": f"T{i}",
            "client": {"id": 1889559, "name": "COND. SQB"},
            "stage": {"id": 1, "name": "Pending" if i % 2 else "Done"},
            "responsible": {"id": 2, "name": "Pedro Martinez"},
            "is_closed": i % 2 == 0,
            "sla_info": {"solve_expiration": "2026-09-17T20:00:00Z", "solved_in_time": None},
        }
        for i in range(total)
    ]

    def responder(path: str, args: dict[str, Any]) -> dict[str, Any]:
        limite, pagina = args.get("limit", 20), args.get("offset", 1)
        return {"value": tickets[(pagina - 1) * limite : pagina * limite], "total_items": total}

    return responder


@pytest.mark.asyncio
async def test_tickets_todas_paginas_varre_no_servidor() -> None:
    client = _ClienteFalso(_paginas_tiflux(450))
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    saida = json.loads(
        await handlers["tiflux_tickets"](
            {"client_ids": ["1889559"], "filter_by": "all", "todas_paginas": True}
        )
    )

    assert sorted(a["offset"] for _, a in client.chamadas) == [1, 2, 3]  # 450 / 200
    resumo = saida["resumo"]
    assert resumo["total_items"] == 450 and resumo["recebidos_nesta_resposta"] == 450
    assert resumo["abertos"] + resumo["fechados"] == 450
    assert resumo["por_estagio"] == {"Pending": 225, "Done": 225}
    assert resumo["por_responsavel"] == {"Pedro Martinez": 450}
    assert "aviso" not in resumo  # cobriu tudo, não há o que avisar


@pytest.mark.asyncio
async def test_tickets_sem_varredura_avisa_que_e_parcial() -> None:
    """O defeito original: o agente via 20 tickets e fazia o relatório como se
    fossem todos. Agora a resposta diz com todas as letras que é uma fatia."""
    client = _ClienteFalso(_paginas_tiflux(496))
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    saida = json.loads(await handlers["tiflux_tickets"]({"client_ids": ["1889559"]}))

    assert len(client.chamadas) == 1
    assert "de 496 tickets" in saida["resumo"]["aviso"]
    assert saida["value"][0]["sla_vence"] == "2026-09-17T20:00:00Z"


@pytest.mark.asyncio
async def test_clientes_do_tiflux_devolvem_id_para_filtrar_tickets() -> None:
    client = _ClienteFalso(
        lambda p, a: {
            "value": [
                {
                    "id": 1889559,
                    "name": "CONDOMINIO SUPERQUADRA BRASILIA SQB",
                    "social": "COND SQB",
                    "social_revenue": "08294694000129",
                    "status": True,
                }
            ],
            "total_items": 1,
            "raw_data": "x" * 5000,
        }
    )
    handlers = montar_handlers_mcpai(client)  # type: ignore[arg-type]

    saida = json.loads(await handlers["tiflux_clientes"]({"name": "SQB"}))

    assert client.chamadas[0] == ("/api/tiflux/list/clients", {"name": "SQB"})
    assert saida["value"] == [
        {"id": 1889559, "nome": "CONDOMINIO SUPERQUADRA BRASILIA SQB", "cnpj": "08294694000129"}
    ]
