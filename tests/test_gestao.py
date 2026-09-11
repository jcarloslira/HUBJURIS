"""Testes da gestão condominial: coleta diária, diário e ferramentas hub_*."""

import json
from datetime import date
from typing import Any

import pytest

from app.agents.ferramentas_gestao import FERRAMENTAS_GESTAO, montar_handlers_gestao
from app.services.gestao import (
    GestaoError,
    GestaoService,
    andamento,
    contem_nome,
    eventos_de_processo,
    eventos_de_ticket,
    mesmo_condominio,
    parece_condominio,
)
from tests.banco_falso import BancoFalso

ESC = "esc-1"


# ─── Nomes ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("a", "b", "esperado"),
    [
        # Casos reais EasyJur × Tiflux do escritório.
        ("CONDOMINIO SUPERQUADRA BRASILIA", "CONDOMINIO SUPERQUADRA BRASILIA SQB", True),
        ("Condomínio Vila Park", "CONDOMINIO VILA PARK", True),
        ("CONQUISTA RESIDENCIAL VILLE QUADRA 03", "CONQUISTA RESIDENCIAL VILLE QUADRA 04", False),
        ("CONDOMINIO RESIDENCIAL COLINAS IX", "CONDOMINIO RESIDENCIAL COLINAS", False),
        ("CONDOMINIO MORADA NOBRE", "CONDOMINIO MORADA IMPERIAL", False),
    ],
)
def test_mesmo_condominio(a: str, b: str, esperado: bool) -> None:
    assert mesmo_condominio(a, b) is esperado


def test_nome_curto_contido_so_casa_sem_mudar_de_unidade() -> None:
    assert contem_nome("CONDOMINIO CASABLANCA MALL RESIDENCE", "COND. RESIDENCIAL CASABLANCA")
    assert not contem_nome("CONDOMINIO COLINAS IX", "CONDOMINIO COLINAS")


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("CONDOMINIO CITTA", True),
        ("COND. SHCGN 710 BL A", True),
        ("TJDFT", False),
        ("PERITO ANDRÉ DIAS", False),
        ("EASYJUR SOFTWARE JURIDICO INTELIGENTE", False),
    ],
)
def test_so_condominio_do_tiflux_vira_condominio(nome: str, esperado: bool) -> None:
    assert parece_condominio(nome) is esperado


# ─── Eventos ─────────────────────────────────────────────────────────────────


def _processo(**extra: Any) -> dict[str, Any]:
    base = {
        "id_processo": 77,
        "numero": "0701234-11.2026.8.07.0014",
        "titulo_acao": "Cobrança de cotas",
        "nome_contrario": "Fulano",
        "status_label": "Ativo",
        "valor_causa": "15462.33",
        "vara": "Vara Cível do Guará",
        "uf": "DF",
        "cliente_info": {"id": 5467753, "nome": "CONDOMINIO MORADA NOBRE"},
        "id_cliente": 5467753,
        "data_distribuicao": "2026-08-07",
        "ultimo_andamento": "08/09/2026 - <p>Cita&ccedil;&atilde;o expedida</p>",
    }
    return {**base, **extra}


def test_andamento_separa_data_e_limpa_html() -> None:
    assert andamento("08/09/2026 - <p>Cita&ccedil;&atilde;o expedida</p>") == (
        "2026-09-08",
        "Citação expedida",
    )
    assert andamento("sem data") == (None, "sem data")


def test_processo_gera_novo_e_andamento_com_chaves_estaveis() -> None:
    eventos = {e["tipo"]: e for e in eventos_de_processo(_processo())}

    assert eventos["processo_novo"]["ocorrido_em"] == "2026-08-07"
    assert eventos["processo_novo"]["valor"] == 15462.33
    assert eventos["processo_novo"]["chave"] == "ej:novo:77"
    assert eventos["andamento"]["ocorrido_em"] == "2026-09-08"
    assert eventos["andamento"]["titulo"] == "Citação expedida"
    # Mesmo andamento lido de novo amanhã = mesma chave (não duplica no diário).
    assert eventos_de_processo(_processo())[1]["chave"] == eventos["andamento"]["chave"]
    assert "processo_encerrado" not in eventos


def test_processo_encerrado_entra_no_diario() -> None:
    tipos = [e["tipo"] for e in eventos_de_processo(_processo(data_encerramento="2026-09-01"))]
    assert "processo_encerrado" in tipos


def test_ticket_fechado_gera_abertura_e_encerramento() -> None:
    ticket = {
        "ticket_number": 6400,
        "title": "Vazamento no bloco B",
        "created_at": "2026-09-01T12:00:00Z",
        "updated_at": "2026-09-03T15:00:00Z",
        "is_closed": True,
        "desk": {"id": 1, "name": "Demandas Gerais"},
        "responsible": {"id": 2, "name": "Pedro Martinez"},
        "client": {"id": 1889559, "name": "CONDOMINIO SUPERQUADRA BRASILIA SQB"},
    }

    eventos = {e["tipo"]: e for e in eventos_de_ticket(ticket)}

    assert eventos["ticket_aberto"]["ocorrido_em"] == "2026-09-01"
    assert eventos["ticket_fechado"]["ocorrido_em"] == "2026-09-03"
    assert "Pedro Martinez" in eventos["ticket_aberto"]["descricao"]


# ─── Coleta ponta a ponta (APIs e banco falsos) ──────────────────────────────


class _MCPFalso:
    ativo = True

    def __init__(self) -> None:
        self.processos = [
            _processo(),
            _processo(id_processo=78, numero="0709999-00.2026.8.07.0014",
                      status_label="Baixado", data_encerramento="2026-09-02"),
            _processo(id_processo=90, numero="0000001-00.2025.5.10.0104",
                      cliente_info={"id": 1, "nome": "CONDOMINIO SUPERQUADRA BRASILIA"},
                      id_cliente=1, valor_causa="437959.67"),
        ]
        self.clientes = [
            {"id": 1889559, "name": "CONDOMINIO SUPERQUADRA BRASILIA SQB"},
            {"id": 555, "name": "TJDFT"},
            {"id": 556, "name": "CONDOMINIO CITTA"},
        ]
        self.abertos = [
            {"ticket_number": 10, "title": "Portão", "created_at": "2026-09-10T10:00:00Z",
             "is_closed": False, "client": {"id": 1889559}},
        ]
        self.chamadas: list[tuple[str, dict[str, Any]]] = []

    async def chamar(self, path: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        self.chamadas.append((path, args))
        if path.endswith("/list/processos"):
            return {"data": self.processos, "meta": {"total": 3, "total_pages": 1}}
        if path.endswith("/list/clients"):
            return {"value": self.clientes, "total_items": 3}
        if args.get("filter_by") == "open":
            return {"value": self.abertos, "total_items": len(self.abertos)}
        fechado = {"ticket_number": 9, "title": "Cobrança", "created_at": "2026-09-01T10:00:00Z",
                   "updated_at": "2026-09-05T10:00:00Z", "is_closed": True,
                   "client": {"id": 555}}
        return {"value": [*self.abertos, fechado], "total_items": 2}


@pytest.mark.asyncio
async def test_coleta_cria_condominios_vincula_e_nao_duplica() -> None:
    banco, mcp = BancoFalso(), _MCPFalso()
    svc = GestaoService(banco, mcp)  # type: ignore[arg-type]

    resumo = await svc.sincronizar(ESC)

    condominios = {c["nome"]: c for c in banco.tabelas["condominios"]}
    # EasyJur cria os clientes; o SQB do Tiflux casa com o do EasyJur.
    assert condominios["CONDOMINIO SUPERQUADRA BRASILIA"]["tiflux_cliente_id"] == "1889559"
    assert "CONDOMINIO CITTA" in condominios  # condomínio só do Tiflux
    assert "TJDFT" not in condominios  # tribunal não vira condomínio
    assert resumo["completa"] is True
    eventos = banco.tabelas["eventos_condominio"]
    tipos = sorted(e["tipo"] for e in eventos)
    assert tipos.count("processo_novo") == 3
    assert "processo_encerrado" in tipos and "ticket_fechado" in tipos
    # Ticket do TJDFT fica no diário sem vínculo.
    assert any(e["referencia"] == "#9" and e["condominio_id"] is None for e in eventos)
    fotos = {f["condominio_id"]: f for f in banco.tabelas["fotos_diarias"]}
    sqb = condominios["CONDOMINIO SUPERQUADRA BRASILIA"]["id"]
    assert fotos[sqb]["tickets_abertos"] == 1
    assert fotos[sqb]["valor_causas_ativas"] == 437959.67

    total = len(eventos)
    segunda = await svc.sincronizar(ESC)

    assert segunda["eventos_novos"] == 0
    assert len(banco.tabelas["eventos_condominio"]) == total
    assert segunda["completa"] is False  # a 2ª coleta só relê os tickets recentes


@pytest.mark.asyncio
async def test_ticket_que_sumiu_dos_abertos_vira_encerramento() -> None:
    banco, mcp = BancoFalso(), _MCPFalso()
    svc = GestaoService(banco, mcp)  # type: ignore[arg-type]
    await svc.sincronizar(ESC)

    mcp.abertos = []  # o ticket 10 foi encerrado entre uma coleta e outra
    await svc.sincronizar(ESC)

    assert any(
        e["chave"] == "tf:fe:10" for e in banco.tabelas["eventos_condominio"]
    )


# ─── Ferramentas do agente ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ferramentas_leem_e_escrevem_no_hub() -> None:
    banco, mcp = BancoFalso(), _MCPFalso()
    svc = GestaoService(banco, mcp)  # type: ignore[arg-type]
    await svc.sincronizar(ESC)
    h = montar_handlers_gestao(svc, ESC)

    ficha = json.loads(await h["hub_condominio"]({"nome": "superquadra brasília"}))
    assert ficha["cadastro"]["nome"] == "CONDOMINIO SUPERQUADRA BRASILIA"
    assert ficha["foto_atual"]["processos_ativos"] == 1

    saida = await h["hub_atualizar_condominio"](
        {"condominio": "Superquadra Brasilia", "sindico": "Sr. Pedro (61) 99999-0000"}
    )
    assert "Sr. Pedro" in saida

    await h["hub_anotar"]({"condominio": "Superquadra", "titulo": "Assembleia aprovou obra",
                           "dia": "10/09/2026"})
    diario = json.loads(await h["hub_diario"](
        {"data_inicio": "01/09/2026", "data_fim": "2026-09-30", "condominio": "Superquadra"}
    ))
    assert diario["resumo"]["por_tipo"]["Anotação"] == 1
    assert diario["condominio"] == "CONDOMINIO SUPERQUADRA BRASILIA"


@pytest.mark.asyncio
async def test_nome_ambiguo_pede_para_escolher() -> None:
    banco, mcp = BancoFalso(), _MCPFalso()
    svc = GestaoService(banco, mcp)  # type: ignore[arg-type]
    await svc.sincronizar(ESC)

    with pytest.raises(GestaoError) as erro:
        await svc.buscar_condominio(ESC, "condominio")
    assert erro.value.status == 409

    saida = await montar_handlers_gestao(svc, ESC)["hub_condominio"]({"nome": "inexistente"})
    assert "Nenhum condomínio" in saida


@pytest.mark.asyncio
async def test_diario_de_periodo_resume_por_tipo_e_valor() -> None:
    banco, mcp = BancoFalso(), _MCPFalso()
    svc = GestaoService(banco, mcp)  # type: ignore[arg-type]
    await svc.sincronizar(ESC)

    agosto = await svc.eventos(ESC, inicio=date(2026, 8, 1), fim=date(2026, 8, 31))

    assert agosto["resumo"]["por_tipo"]["Processo novo"] == 3
    assert agosto["resumo"]["valor_processos_novos"] == round(15462.33 * 2 + 437959.67, 2)


def test_catalogo_das_ferramentas_de_gestao() -> None:
    nomes = {f["name"] for f in FERRAMENTAS_GESTAO}
    assert nomes == {
        "hub_painel", "hub_diario", "hub_condominios", "hub_condominio",
        "hub_atualizar_condominio", "hub_anotar", "hub_coletar",
    }
    for ferramenta in FERRAMENTAS_GESTAO:
        assert ferramenta["input_schema"]["type"] == "object"
