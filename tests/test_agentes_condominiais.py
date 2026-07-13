"""Testes das personas dos agentes condominiais."""

import importlib.util

from app.agents.consulta_historica import ConsultaHistoricaAgent
from app.agents.contratos import ContratosAgent
from app.agents.juridico_geral import JuridicoGeralAgent
from app.agents.notificacoes import NotificacoesAgent
from app.agents.pareceres import PareceresAgent
from app.agents.peticoes import PeticoesAgent
from app.agents.supervisor import SupervisorAgent


def test_supervisor_tem_prompt_de_onboarding() -> None:
    agente = SupervisorAgent(client=None)  # type: ignore[arg-type]
    prompt = agente.system_prompt.lower()
    assert "onboarding" in prompt
    assert "condominial" in prompt
    assert agente.max_tokens >= 1024


def test_especialistas_sao_condominiais() -> None:
    casos = [
        (NotificacoesAgent, "notifica"),
        (PeticoesAgent, "cotas condominiais"),
        (ContratosAgent, "rescisão"),
        (PareceresAgent, "parecer"),
        (ConsultaHistoricaAgent, "síndico"),
        (JuridicoGeralAgent, "condominial"),
    ]
    for classe, termo in casos:
        agente = classe(client=None)  # type: ignore[arg-type]
        prompt = agente.system_prompt.lower()
        assert "condominial" in prompt, classe.__name__
        assert termo in prompt, classe.__name__
        assert agente.max_tokens >= 1024


def test_processos_foi_removido() -> None:
    assert importlib.util.find_spec("app.agents.processos") is None
