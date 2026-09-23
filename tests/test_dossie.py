"""Dossiê da tratativa: o que já houve com aquele condomínio, antes de escrever.

O que se prova aqui é o comportamento que o Dr. Wilker pediu: ao tratar de uma
unidade, o agente já chega sabendo a última peça enviada, o último movimento do
processo e onde a conversa anterior parou, numa consulta só.
"""

from typing import Any

import pytest

from app.agents.ferramentas_dossie import FERRAMENTAS_DOSSIE, montar_handlers_dossie
from app.services.gestao import GestaoService
from app.services.memoria import MemoriaService
from tests.banco_falso import BancoFalso

ESC = "esc-1"
CID = "cond-1"


class DriveFalso:
    """Composio de mentira: devolve os arquivos que o teste mandar."""

    def __init__(self, arquivos: list[dict[str, Any]] | None = None, quebra: bool = False):
        self.arquivos = arquivos or []
        self.quebra = quebra
        self.consultas: list[str] = []

    async def executar_acao(self, _acao: str, _entidade: str, args: dict[str, Any]) -> Any:
        if self.quebra:
            raise RuntimeError("Drive fora do ar")
        self.consultas.append(args.get("q", ""))
        return {"files": self.arquivos}


def _banco() -> BancoFalso:
    banco = BancoFalso()
    banco.tabelas["escritorios"] = [{"id": ESC, "usa_easyjur_tiflux": True}]
    banco.tabelas["condominios"] = [
        {"id": CID, "escritorio_id": ESC, "nome": "CONDOMINIO RESIDENCIAL VENTURA",
         "sindico": "Marcos Lima", "administradora": "Predial DF", "cidade": "Brasília"},
        {"id": "cond-2", "escritorio_id": ESC, "nome": "CONDOMINIO VILA PARK"},
    ]
    banco.tabelas["condominio_fatos"] = [
        {"escritorio_id": ESC, "condominio_id": CID, "origem": "agente",
         "fato": "O síndico não autoriza acordo com a unidade 204-B.",
         "created_at": "2026-08-01T10:00:00+00:00"},
    ]
    banco.tabelas["eventos_condominio"] = [
        {"escritorio_id": ESC, "condominio_id": CID, "fonte": "easyjur", "tipo": "andamento",
         "referencia": "0712345-11.2025.8.07.0020", "titulo": "Decorrido prazo da unidade 204-B",
         "descricao": "", "valor": None, "ocorrido_em": "2026-09-10"},
        {"escritorio_id": ESC, "condominio_id": CID, "fonte": "tiflux", "tipo": "ticket_aberto",
         "referencia": "5251", "titulo": "Dúvida sobre taxa extra", "descricao": "",
         "valor": None, "ocorrido_em": "2026-09-12"},
    ]
    banco.tabelas["interacoes"] = [
        {"escritorio_id": ESC, "condominio_id": CID, "agente": "notificacoes",
         "assunto": "Notificação da unidade 204-B", "onde_parou": "Aguardando o AR voltar",
         "proximo_passo": "Ajuizar se não houver resposta até 30/09",
         "created_at": "2026-09-11T09:00:00+00:00"},
    ]
    return banco


def _handlers(banco: BancoFalso, drive: DriveFalso | None = None):
    return montar_handlers_dossie(
        GestaoService(banco, None),
        MemoriaService(banco, None),
        ESC,
        drive,
    )


def test_a_ferramenta_manda_o_agente_consultar_antes_de_redigir() -> None:
    """A descrição é o que faz o modelo chamar: sem "ANTES", ele pula a consulta."""
    descricao = FERRAMENTAS_DOSSIE[0]["description"]

    assert "ANTES" in descricao
    assert "unidade" in FERRAMENTAS_DOSSIE[0]["input_schema"]["properties"]


@pytest.mark.asyncio
async def test_dossie_traz_cadastro_memoria_demandas_e_movimentos() -> None:
    handlers = _handlers(_banco())

    texto = await handlers["dossie_da_demanda"]({"condominio": "Ventura"})

    assert "Marcos Lima" in texto  # cadastro
    assert "não autoriza acordo" in texto  # o que o escritório já sabe
    assert "Aguardando o AR voltar" in texto  # onde parou a demanda anterior
    assert "Decorrido prazo" in texto  # movimento do EasyJur
    assert "10/09/2026" in texto  # com data, para o agente citar


@pytest.mark.asyncio
async def test_com_unidade_o_que_e_daquela_unidade_vem_primeiro() -> None:
    banco = _banco()
    drive = DriveFalso(
        [
            {"id": "f2", "name": "Convenção Ventura.pdf", "modifiedTime": "2026-01-05T10:00:00Z"},
            {"id": "f1", "name": "Notificação 204-B Ventura.docx",
             "modifiedTime": "2026-08-12T10:00:00Z"},
        ]
    )
    handlers = _handlers(banco, drive)

    texto = await handlers["dossie_da_demanda"]({"condominio": "Ventura", "unidade": "204-B"})

    linhas = [linha for linha in texto.split("\n") if "[id:" in linha]
    assert "204-B" in linhas[0], "a peça daquela unidade é a que interessa"
    assert "12/08/2026" in linhas[0]


@pytest.mark.asyncio
async def test_a_busca_no_drive_procura_pela_unidade_tambem() -> None:
    drive = DriveFalso()
    handlers = _handlers(_banco(), drive)

    await handlers["dossie_da_demanda"]({"condominio": "Ventura", "unidade": "Bloco C apto 42"})

    assert "42" in drive.consultas[0]
    assert "VENTURA" in drive.consultas[0].upper()


@pytest.mark.asyncio
async def test_drive_fora_do_ar_nao_derruba_o_dossie() -> None:
    """O histórico do Hub sozinho já vale a consulta: não pode ir tudo por água abaixo."""
    handlers = _handlers(_banco(), DriveFalso(quebra=True))

    texto = await handlers["dossie_da_demanda"]({"condominio": "Ventura"})

    assert "Aguardando o AR voltar" in texto


@pytest.mark.asyncio
async def test_condominio_fora_do_hub_ainda_busca_no_acervo() -> None:
    drive = DriveFalso(
        [{"id": "f9", "name": "Contrato Solaris.docx", "modifiedTime": "2026-05-02T10:00:00Z"}]
    )
    handlers = _handlers(_banco(), drive)

    texto = await handlers["dossie_da_demanda"]({"condominio": "Solaris"})

    assert "Contrato Solaris.docx" in texto
    assert "Siga com a tarefa" in texto


@pytest.mark.asyncio
async def test_sem_condominio_informado_pede_o_nome() -> None:
    handlers = _handlers(_banco())

    assert "Informe o condomínio" in await handlers["dossie_da_demanda"]({})
