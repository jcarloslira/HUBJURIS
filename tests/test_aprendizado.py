"""O agente aprende com o escritório e não esquece.

A prova que importa: o Dr. Wilker corrige uma vez e a correção reaparece no
prompt da conversa seguinte, sem ninguém repetir.
"""

import pytest

from app.agents.ferramentas_aprendizado import montar_handlers_aprendizado
from app.services.aprendizado import AprendizadoService, mesma_regra, parece_instrucao
from tests.banco_falso import BancoFalso

ESCRITORIO = "esc-1"
OUTRO = "esc-2"

SEM_AGENDA = (
    "Em relatório ao síndico, nunca criar seção de agenda ou de prazos futuros; "
    "o compromisso entra no Próximo passo do próprio item."
)


@pytest.fixture
def servico() -> AprendizadoService:
    return AprendizadoService(BancoFalso())


@pytest.mark.parametrize(
    "mensagem",
    [
        "não ponha seção de agenda no relatório",
        "SEMPRE assine com a OAB de quem gerou",
        "de agora em diante o foro é Brasília",
        "prefiro que você mande a planilha junto",
        "o certo é citar o art. 292",
    ],
)
def test_ordem_do_escritorio_liga_o_aprendizado(mensagem: str) -> None:
    assert parece_instrucao(mensagem)


@pytest.mark.parametrize(
    "mensagem",
    [
        "faça o relatório do Ventura de setembro",
        "bom dia, o que temos hoje?",
        "qual o prazo para impugnar o laudo?",
    ],
)
def test_pedido_comum_nao_vira_regra(mensagem: str) -> None:
    """Sem isto, todo pedido viraria "regra" e o prompt viraria lixo."""
    assert not parece_instrucao(mensagem)


@pytest.mark.asyncio
async def test_regra_aprendida_volta_no_prompt(servico: AprendizadoService) -> None:
    await servico.aprender(ESCRITORIO, SEM_AGENDA, escopo="relatorio")

    bloco = await servico.bloco(ESCRITORIO)
    assert "seção de agenda" in bloco
    assert "PREVALECEM sobre o padrão geral" in bloco


@pytest.mark.asyncio
async def test_escritorio_nao_ve_regra_de_outro(servico: AprendizadoService) -> None:
    """Regra é método de um escritório: vazar para outro seria o mesmo que vazar dado."""
    await servico.aprender(ESCRITORIO, SEM_AGENDA)

    assert await servico.bloco(OUTRO) == ""


@pytest.mark.asyncio
async def test_a_mesma_ordem_dita_de_outro_jeito_nao_duplica(
    servico: AprendizadoService,
) -> None:
    primeira = await servico.aprender(ESCRITORIO, SEM_AGENDA)
    segunda = await servico.aprender(
        ESCRITORIO,
        "Nunca criar seção de agenda nem de prazos futuros no relatório ao síndico: "
        "o compromisso entra no Próximo passo do item.",
    )

    assert primeira is not None
    assert segunda is None  # já sabia
    assert len(await servico.listar(ESCRITORIO)) == 1


@pytest.mark.asyncio
async def test_regra_curta_demais_nao_entra(servico: AprendizadoService) -> None:
    assert await servico.aprender(ESCRITORIO, "ok") is None


@pytest.mark.asyncio
async def test_escopo_inventado_vira_geral(servico: AprendizadoService) -> None:
    await servico.aprender(ESCRITORIO, SEM_AGENDA, escopo="qualquer-coisa")

    assert (await servico.listar(ESCRITORIO))[0]["escopo"] == "geral"


@pytest.mark.asyncio
async def test_esquecer_tira_a_regra_do_prompt(servico: AprendizadoService) -> None:
    await servico.aprender(ESCRITORIO, SEM_AGENDA)

    saiu = await servico.esquecer(ESCRITORIO, "seção de agenda")

    assert saiu == [SEM_AGENDA]
    assert await servico.bloco(ESCRITORIO) == ""


@pytest.mark.asyncio
async def test_esquecer_o_que_nao_existe_nao_derruba_nada(
    servico: AprendizadoService,
) -> None:
    await servico.aprender(ESCRITORIO, SEM_AGENDA)

    assert await servico.esquecer(ESCRITORIO, "coisa que nunca foi dita") == []
    assert len(await servico.listar(ESCRITORIO)) == 1


def test_regras_sobre_assuntos_diferentes_nao_se_confundem() -> None:
    assert not mesma_regra(SEM_AGENDA, "Sempre assinar com a OAB de quem gerou o relatório.")


@pytest.mark.asyncio
async def test_ferramenta_grava_e_manda_confirmar_ao_usuario() -> None:
    servico = AprendizadoService(BancoFalso())
    handlers = montar_handlers_aprendizado(servico, ESCRITORIO, "user-1")

    resposta = await handlers["aprender"]({"regra": SEM_AGENDA, "escopo": "relatorio"})

    assert "Aprendido" in resposta
    assert "Confirme ao usuário" in resposta
    assert len(await servico.listar(ESCRITORIO)) == 1


@pytest.mark.asyncio
async def test_ferramenta_lista_o_que_foi_aprendido() -> None:
    servico = AprendizadoService(BancoFalso())
    handlers = montar_handlers_aprendizado(servico, ESCRITORIO)
    await servico.aprender(ESCRITORIO, SEM_AGENDA)

    resposta = await handlers["aprendizados"]({})

    assert "seção de agenda" in resposta


@pytest.mark.asyncio
async def test_sem_nada_aprendido_a_ferramenta_convida_a_ensinar() -> None:
    handlers = montar_handlers_aprendizado(AprendizadoService(BancoFalso()), ESCRITORIO)

    resposta = await handlers["aprendizados"]({})

    assert "ainda não te ensinou" in resposta
