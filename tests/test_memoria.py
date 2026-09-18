"""Testes da memória viva: o agente lembra entre conversas e registra sozinho."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.memoria import MemoriaService, fato_repetido
from tests.banco_falso import BancoFalso

ESC = "esc-1"
COND = "cond-sqb"


def _banco() -> BancoFalso:
    banco = BancoFalso()
    banco.tabelas["condominios"] = [
        {"id": COND, "escritorio_id": ESC, "nome": "Condomínio Superquadra Brasília",
         "sindico": "Sr. Pedro", "administradora": None},
        {"id": "cond-vp", "escritorio_id": ESC, "nome": "Condomínio Vila Park"},
    ]
    return banco


class _IAFalsa:
    """Modelo de extração: devolve o JSON combinado e guarda o que recebeu."""

    def __init__(self, resposta: dict[str, Any] | str) -> None:
        self.resposta = resposta
        self.recebido: str = ""
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw: Any) -> SimpleNamespace:
        self.recebido = kw["messages"][0]["content"]
        texto = (
            self.resposta if isinstance(self.resposta, str) else json.dumps(self.resposta)
        )
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)])


_TURNO = {
    "condominio": "Superquadra Brasília",
    "assunto": "Impugnação à gratuidade na execução da unidade 301",
    "onde_parou": "Peça entregue; falta o Dr. Wilker revisar e protocolar.",
    "proximo_passo": "Protocolar até sexta",
    "fatos": ["A síndica do SQB é a Sra. Marta desde agosto de 2026."],
}


@pytest.mark.asyncio
async def test_turno_vira_memoria_com_onde_parou_e_fato() -> None:
    banco, ia = _banco(), _IAFalsa(_TURNO)
    svc = MemoriaService(banco, ia)  # type: ignore[arg-type]

    await svc.registrar(
        ESC,
        user_id="u1",
        agente="peticoes",
        pedido="Faça a impugnação à gratuidade do SQB",
        resposta="x" * 500,
    )

    registro = banco.tabelas["interacoes"][0]
    assert registro["condominio_id"] == COND  # ligou ao condomínio certo
    assert registro["onde_parou"].startswith("Peça entregue")
    assert registro["proximo_passo"] == "Protocolar até sexta"
    assert banco.tabelas["condominio_fatos"][0]["fato"].startswith("A síndica do SQB")


@pytest.mark.asyncio
async def test_fato_ja_conhecido_nao_entra_de_novo() -> None:
    """Sem isso, a memória do condomínio viraria a mesma frase repetida 50 vezes."""
    banco, ia = _banco(), _IAFalsa(_TURNO)
    banco.tabelas["condominio_fatos"] = [
        {"escritorio_id": ESC, "condominio_id": COND,
         "fato": "A síndica do SQB é a Sra. Marta desde agosto de 2026."}
    ]
    svc = MemoriaService(banco, ia)  # type: ignore[arg-type]

    await svc.registrar(ESC, user_id=None, agente="peticoes", pedido="p", resposta="x" * 500)

    assert len(banco.tabelas["condominio_fatos"]) == 1


@pytest.mark.asyncio
async def test_resposta_curta_nao_vira_memoria() -> None:
    """Saudação e pedido de esclarecimento não são demanda; não gastam modelo nem linha."""
    banco, ia = _banco(), _IAFalsa(_TURNO)
    svc = MemoriaService(banco, ia)  # type: ignore[arg-type]

    await svc.registrar(ESC, user_id=None, agente="supervisor", pedido="oi", resposta="Olá!")

    assert not banco.tabelas.get("interacoes")
    assert ia.recebido == ""


@pytest.mark.asyncio
async def test_extracao_sem_json_valido_nao_derruba_nada() -> None:
    banco, ia = _banco(), _IAFalsa("desculpe, não consegui")
    svc = MemoriaService(banco, ia)  # type: ignore[arg-type]

    await svc.registrar(ESC, user_id=None, agente="peticoes", pedido="p", resposta="x" * 500)

    assert not banco.tabelas.get("interacoes")


@pytest.mark.asyncio
async def test_contexto_traz_ultimas_demandas_e_a_ficha_do_condominio_citado() -> None:
    banco = _banco()
    banco.tabelas["interacoes"] = [
        {"escritorio_id": ESC, "condominio_id": COND, "agente": "peticoes",
         "assunto": "Impugnação à gratuidade", "onde_parou": "Aguardando protocolo",
         "proximo_passo": "Protocolar até sexta", "created_at": "2026-09-17T10:00:00+00:00"},
        {"escritorio_id": ESC, "condominio_id": "cond-vp", "agente": "notificacoes",
         "assunto": "Notificação de barulho", "onde_parou": "Entregue ao síndico",
         "created_at": "2026-09-16T10:00:00+00:00"},
    ]
    banco.tabelas["condominio_fatos"] = [
        {"escritorio_id": ESC, "condominio_id": COND, "created_at": "2026-09-01",
         "fato": "Convenção veda locação por temporada."}
    ]
    banco.tabelas["eventos_condominio"] = [
        {"escritorio_id": ESC, "condominio_id": COND, "ocorrido_em": "2026-09-15",
         "tipo": "andamento", "referencia": "0701234-11.2026.8.07.0014",
         "titulo": "Citação expedida"}
    ]
    svc = MemoriaService(banco)  # type: ignore[arg-type]

    texto = await svc.contexto(ESC, "como ficou a execução do Superquadra Brasília?")

    assert "MEMÓRIA DO ESCRITÓRIO" in texto
    assert "17/09/2026" in texto and "parou em: Aguardando protocolo" in texto
    assert "Notificação de barulho" in texto  # lembra de outros condomínios também
    assert "MEMÓRIA DO CONDOMÍNIO Condomínio Superquadra Brasília" in texto
    assert "Sr. Pedro" in texto  # cadastro
    assert "Convenção veda locação por temporada." in texto
    assert "Citação expedida" in texto


@pytest.mark.asyncio
async def test_sem_condominio_citado_so_vem_o_historico_geral() -> None:
    banco = _banco()
    banco.tabelas["interacoes"] = [
        {"escritorio_id": ESC, "condominio_id": None, "agente": "juridico-geral",
         "assunto": "Dúvida sobre prescrição", "created_at": "2026-09-17T10:00:00+00:00"}
    ]
    svc = MemoriaService(banco)  # type: ignore[arg-type]

    texto = await svc.contexto(ESC, "o que diz a lei sobre prescrição intercorrente?")

    assert "MEMÓRIA DO ESCRITÓRIO" in texto
    assert "MEMÓRIA DO CONDOMÍNIO" not in texto


@pytest.mark.asyncio
async def test_escritorio_sem_historico_nao_polui_o_prompt() -> None:
    svc = MemoriaService(_banco())  # type: ignore[arg-type]

    assert await svc.contexto(ESC, "bom dia") == ""


def test_fato_repetido_tolera_reescrita() -> None:
    assert fato_repetido(
        "A síndica do SQB é a Sra. Marta desde agosto de 2026.",
        "A síndica do SQB é a Sra. Marta, desde agosto de 2026",
    )
    assert not fato_repetido(
        "A síndica do SQB é a Sra. Marta.", "A administradora do SQB é a Lisboa Gestão."
    )
