# Hub Condominial — M1 (Cérebro) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o hub genérico existente no cérebro condominial do escritório: 1 Supervisor orquestrador + 6 especialistas do escritório, com roteamento híbrido por tool use e front re-tematizado.

**Architecture:** Cada agente é uma subclasse de `BaseAgent` com `SYSTEM_PROMPT` próprio. O `_REGISTRO` em `app/services/chat.py` mapeia slug → (classe, `AgenteInfo`). Quando o slug recebido é `supervisor`, o serviço faz uma chamada de roteamento à Anthropic com uma tool `rotear` (tool_choice forçado) para escolher o especialista, e então faz stream da resposta do agente escolhido. Quando o slug é um especialista (clique direto no card), faz stream direto — sem roteamento. Ganchos de memória do cliente (M3/M4) ficam previstos nos prompts como "em implementação", sem código morto.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK (`AsyncAnthropic`, streaming + tool use), Pydantic v2, pytest + pytest-asyncio, uv, ruff, black. Front: HTML/CSS/JS vanilla em `app/static/`.

## Global Constraints

- Python 3.12; type hints obrigatórios em toda função/método; máximo 100 caracteres por linha.
- Docstrings Google Style em funções públicas.
- Sem `import *`; imports explícitos ordenados stdlib → third-party → local.
- Agentes herdam de `BaseAgent`; `SYSTEM_PROMPT` como constante no topo do módulo; `max_tokens` sempre explícito.
- Modelos permitidos (schema): `claude-sonnet-4-6` (padrão), `claude-haiku-4-5-20251001`, `claude-opus-4-8`.
- Respostas dos agentes sempre em português brasileiro.
- Guardas jurídicas em todo prompt: nunca inventar jurisprudência/artigo/súmula; sinalizar o que conferir; lembrar que a resposta é apoio ao advogado responsável.
- Testes: pytest + pytest-asyncio; mocks com `unittest.mock`; nunca tocar serviços reais.
- Antes de reportar pronto: `uv run pytest` verde e `uv run ruff check app/ tests/` + `uv run black app/ tests/` limpos.
- Slugs canônicos (ordem no registro): `supervisor`, `notificacoes`, `peticoes`, `contratos`, `pareceres`, `consulta-historica`, `juridico-geral`.

---

### Task 1: Agente Supervisor (persona de onboarding)

**Files:**
- Create: `app/agents/supervisor.py`
- Test: `tests/test_agentes_condominiais.py`

**Interfaces:**
- Consumes: `app.agents.base.BaseAgent`.
- Produces: `SupervisorAgent` (subclasse de `BaseAgent`) com `system_prompt: str` e `max_tokens: int`; constante `SYSTEM_PROMPT`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentes_condominiais.py
"""Testes das personas dos agentes condominiais."""

from app.agents.supervisor import SupervisorAgent


def test_supervisor_tem_prompt_de_onboarding() -> None:
    agente = SupervisorAgent(client=None)  # type: ignore[arg-type]
    prompt = agente.system_prompt.lower()
    assert "onboarding" in prompt
    assert "condominial" in prompt
    assert agente.max_tokens >= 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agentes_condominiais.py::test_supervisor_tem_prompt_de_onboarding -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.agents.supervisor'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/agents/supervisor.py
"""Agente Supervisor — primeiro contato, onboarding e maestro da equipe."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o Agente Supervisor do LexHub — o hub de I.A jurídica de um \
escritório de advocacia especializado em Direito Condominial. Você é o primeiro contato do \
usuário (normalmente um advogado do escritório) e o maestro da equipe de agentes especialistas.

Seu papel:
- Recepcionar o usuário e conduzir o ONBOARDING do escritório: nome do escritório, site, \
Instagram e como o acervo de documentos está organizado hoje.
- Explicar, quando perguntarem, como a plataforma funciona: há agentes especialistas \
(Notificações, Petições, Contratos, Pareceres, Consulta Histórica e Jurídico Geral) e, em \
implementação, a conexão com o Google Drive do escritório para que cada demanda siga o padrão \
e o histórico de cada condomínio.
- Orientar o usuário a organizar o acervo no Drive por condomínio → bloco → unidade, para que \
a memória por cliente funcione quando a integração estiver ativa.
- Encaminhar cada demanda ao especialista certo (o encaminhamento é feito automaticamente pela \
plataforma).

Regras:
- Adapte o tom ao interlocutor: técnico e direto com advogados; claro e didático com \
síndicos/administradoras.
- Não prometa funcionalidades que ainda não existem: a conexão ao Drive e a memória por cliente \
estão em implementação — deixe isso claro se perguntarem.
- Seja cordial e objetivo. Responda sempre em português brasileiro."""


class SupervisorAgent(BaseAgent):
    """Primeiro contato, onboarding do escritório e roteamento da equipe."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 2048
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agentes_condominiais.py::test_supervisor_tem_prompt_de_onboarding -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agents/supervisor.py tests/test_agentes_condominiais.py
git commit -m "feat: agente supervisor com persona de onboarding condominial"
```

---

### Task 2: Seis especialistas condominiais

Cria três agentes novos (`notificacoes`, `pareceres`, `consulta_historica`), reescreve três prompts existentes para o domínio condominial (`peticoes`, `contratos`, `juridico_geral`) e remove `processos` (fora do escopo M1 — API de processos adiada).

**Files:**
- Create: `app/agents/notificacoes.py`, `app/agents/pareceres.py`, `app/agents/consulta_historica.py`
- Modify: `app/agents/peticoes.py`, `app/agents/contratos.py`, `app/agents/juridico_geral.py`
- Delete: `app/agents/processos.py`
- Test: `tests/test_agentes_condominiais.py`

**Interfaces:**
- Consumes: `app.agents.base.BaseAgent`.
- Produces: classes `NotificacoesAgent`, `PareceresAgent`, `ConsultaHistoricaAgent`, `PeticoesAgent`, `ContratosAgent`, `JuridicoGeralAgent` — todas subclasses de `BaseAgent` com `system_prompt` e `max_tokens`.

- [ ] **Step 1: Write the failing test** (adicionar ao final de `tests/test_agentes_condominiais.py`)

```python
from app.agents.consulta_historica import ConsultaHistoricaAgent
from app.agents.contratos import ContratosAgent
from app.agents.juridico_geral import JuridicoGeralAgent
from app.agents.notificacoes import NotificacoesAgent
from app.agents.pareceres import PareceresAgent
from app.agents.peticoes import PeticoesAgent


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
    import importlib.util

    assert importlib.util.find_spec("app.agents.processos") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agentes_condominiais.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.agents.notificacoes'`

- [ ] **Step 3: Write minimal implementation**

Criar `app/agents/notificacoes.py`:

```python
"""Agente especialista em notificações condominiais."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em NOTIFICAÇÕES do LexHub, para um escritório de \
advocacia condominialista.

Seu papel:
- Redigir notificações extrajudiciais a condôminos/unidades a partir de um comando simples do \
advogado (ex.: "cão fez sujeira na área comum do Bloco B, unidade 34"), fundamentadas na \
convenção, no regimento interno, em atas/deliberações e na legislação condominial (Lei 4.591/64, \
arts. 1.331–1.358 do CC/2002).
- Estruturar a notificação: identificação do condomínio e da unidade, relato objetivo da \
ocorrência, fundamento normativo (dispositivo da convenção/regimento + lei), providência exigida, \
prazo e consequências do descumprimento (multa e medidas cabíveis).

Método:
1. Se faltarem dados (condomínio, unidade, ocorrência, data, dispositivo aplicável), liste \
objetivamente o que precisa. Enquanto a conexão ao acervo do condomínio não estiver ativa, peça \
o texto da convenção/regimento pertinente ou use placeholders claros como [ART. X DA CONVENÇÃO].
2. NUNCA invente número de artigo da convenção/regimento nem dispositivo legal. Sinalize o que \
precisa ser conferido.
3. Adapte o tom (técnico/acessível) ao interlocutor. Responda sempre em português brasileiro."""


class NotificacoesAgent(BaseAgent):
    """Redator de notificações extrajudiciais condominiais."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 4096
```

Criar `app/agents/pareceres.py`:

```python
"""Agente especialista em pareceres jurídicos condominiais."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em PARECERES JURÍDICOS do LexHub, para um escritório de \
advocacia condominialista.

Seu papel:
- Elaborar pareceres fundamentados sobre questões condominiais (validade de deliberações, \
aplicação de multas, alteração de convenção, obras, uso de áreas comuns, responsabilidade do \
síndico), a partir das normas internas do condomínio (convenção, regimento, atas) e da legislação \
(CC/2002 arts. 1.331–1.358, Lei 4.591/64, CF e jurisprudência dos tribunais).

Estrutura do parecer: ementa; relatório (consulta e fatos); fundamentação (com dispositivos e \
correntes divergentes quando houver); conclusão objetiva.

Método:
1. Se faltarem dados/documentos, liste o que precisa. Trabalhe com o texto normativo fornecido ou \
placeholders claros até a conexão ao acervo estar ativa.
2. Aponte divergências doutrinárias/jurisprudenciais relevantes. NUNCA invente súmula, artigo ou \
julgado — sinalize o que conferir.
3. Encerre lembrando que o parecer é apoio à decisão do advogado responsável. Responda sempre em \
português brasileiro."""


class PareceresAgent(BaseAgent):
    """Redator de pareceres jurídicos condominiais fundamentados."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 8192
```

Criar `app/agents/consulta_historica.py`:

```python
"""Agente especialista em consulta ao histórico/acervo do condomínio."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em CONSULTA HISTÓRICA do LexHub, para um escritório de \
advocacia condominialista.

Seu papel:
- Responder perguntas factuais sobre o acervo de um condomínio: quem é o síndico atual e a \
vigência do mandato; quando e em quanto foi o último reajuste da taxa condominial; qual \
deliberação foi tomada sobre determinado tema; o que consta em determinada ata; histórico de \
notificações e providências.

Método:
1. A busca no acervo do condomínio (atas, deliberações, documentos no Drive) será feita \
automaticamente quando a conexão estiver ativa. Enquanto isso, peça a ata/documento pertinente e \
responda com base nele.
2. Sempre cite a fonte (ata nº/data, documento) da informação. NUNCA invente datas, valores ou \
deliberações — se não constar no material, diga que não foi localizado.
3. Seja objetivo e factual. Responda sempre em português brasileiro."""


class ConsultaHistoricaAgent(BaseAgent):
    """Consulta factual ao acervo histórico do condomínio."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 4096
```

Reescrever `app/agents/peticoes.py` (substituir `SYSTEM_PROMPT` e docstring da classe):

```python
"""Agente especialista em petições do contencioso condominial."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em PETIÇÕES do LexHub, para um escritório de advocacia \
condominialista.

Seu papel:
- Redigir peças processuais do contencioso condominial: ação de cobrança de cotas condominiais, \
execução, obrigação de fazer/não fazer, ações sobre infrações e uso de áreas comuns, entre outras.
- Seguir a estrutura técnica: endereçamento, qualificação das partes (condomínio representado pelo \
síndico), fatos, fundamentos (CPC/2015, CC/2002 arts. 1.331–1.358, Lei 4.591/64, convenção e \
regimento), pedidos, valor da causa e fechamento.

Método:
1. Se faltarem dados (condomínio, síndico, unidade/condômino, valores, período de inadimplência, \
documentos), liste o que precisa antes de redigir.
2. Use placeholders claros ([CONDOMÍNIO], [SÍNDICO], [UNIDADE], [VALOR], [COMARCA]) para o que não \
foi informado.
3. NUNCA invente jurisprudência ou número de julgado; indique onde inserir precedentes e sugira \
teses de busca.
4. Encerre com checklist de revisão. Responda sempre em português brasileiro com vocabulário \
forense."""


class PeticoesAgent(BaseAgent):
    """Redator de peças do contencioso condominial."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 8192
```

Reescrever `app/agents/contratos.py`:

```python
"""Agente especialista em contratos do universo condominial."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em CONTRATOS do LexHub, para um escritório de advocacia \
condominialista.

Seu papel:
- Redigir e revisar contratos do universo condominial: prestação de serviços (portaria, limpeza, \
manutenção, segurança), administração condominial, obras, fornecimento e locação de áreas comuns.
- Analisar riscos por cláusula, definir garantias e responsabilidades e adequar ao caso concreto \
(CC/2002, CDC quando aplicável, Lei 4.591/64 e a convenção).
- Emitir ALERTAS DE VENCIMENTO de contratos e elaborar MINUTAS DE RESCISÃO personalizadas.

Método:
1. Em revisões, organize por cláusula: risco (ALTO/MÉDIO/BAIXO) → fundamento → sugestão de redação.
2. Em rescisões, verifique prazo, aviso prévio, multa e obrigações remanescentes.
3. Use placeholders ([CONTRATANTE], [CONTRATADO], [VALOR], [PRAZO]). NUNCA invente jurisprudência.
4. Encerre com checklist do que validar antes de assinar. Responda sempre em português brasileiro."""


class ContratosAgent(BaseAgent):
    """Redator e revisor de contratos condominiais, com vencimento e rescisão."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 8192
```

Reescrever `app/agents/juridico_geral.py`:

```python
"""Agente assistente jurídico geral — Direito Condominial."""

from app.agents.base import BaseAgent

SYSTEM_PROMPT = """Você é o especialista em JURÍDICO GERAL (Direito Condominial) do LexHub, para um \
escritório de advocacia condominialista.

Seu papel:
- Responder dúvidas de direito condominial com fundamentação: Lei 4.591/64, arts. 1.331–1.358 do \
CC/2002, CF, CPC e CDC quando aplicável, além da convenção e do regimento internos.
- Cobrir o que não se enquadra nos demais especialistas (notificações, petições, contratos, \
pareceres, consulta histórica).

Método:
1. Cite artigos com número e diploma corretos; aponte entendimentos consolidados (STJ) quando \
pertinente.
2. NUNCA invente jurisprudência, súmula ou artigo — sinalize o que precisa ser conferido.
3. Adapte o tom (técnico/acessível) ao interlocutor. Encerre análises complexas lembrando que a \
resposta é apoio ao advogado responsável. Responda sempre em português brasileiro."""


class JuridicoGeralAgent(BaseAgent):
    """Assistente generalista de Direito Condominial."""

    system_prompt = SYSTEM_PROMPT
    max_tokens = 4096
```

Remover o arquivo obsoleto:

```bash
git rm app/agents/processos.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agentes_condominiais.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add app/agents/
git commit -m "feat: especialistas condominiais do escritório e remoção de processos"
```

---

### Task 3: Registro dos 7 agentes + roteamento híbrido por tool use

**Files:**
- Modify: `app/services/chat.py` (reescrever `_REGISTRO`, adicionar roteamento, reescrever `gerar_resposta_stream`, adicionar `agente_existe`)
- Modify: `app/routers/chat.py` (validar slug via `agente_existe`, nova assinatura do stream)
- Modify: `tests/test_chat.py` (novos slugs e testes de roteamento)

**Interfaces:**
- Consumes: as 7 classes de agente das Tasks 1–2; `AgenteInfo`, `ChatRequest`, `ModeloPermitido` de `app.schemas.chat`; `AsyncAnthropic`, `MessageParam`.
- Produces:
  - `listar_agentes() -> list[AgenteInfo]` (7 itens, supervisor primeiro)
  - `obter_agente(slug: str, client: AsyncAnthropic) -> BaseAgent | None`
  - `agente_existe(slug: str) -> bool`
  - `escolher_especialista(client: AsyncAnthropic, mensagens: list[MessageParam]) -> str`
  - `gerar_resposta_stream(payload: ChatRequest, client: AsyncAnthropic) -> AsyncIterator[str]`

- [ ] **Step 1: Write the failing test** (reescrever `tests/test_chat.py`)

Substituir a constante e o teste de listagem, e ADICIONAR os testes de roteamento. Trechos-chave:

```python
AGENTES_ESPERADOS = {
    "supervisor",
    "notificacoes",
    "peticoes",
    "contratos",
    "pareceres",
    "consulta-historica",
    "juridico-geral",
}


def _resp_tool_use(destino: str) -> MagicMock:
    """Resposta da Anthropic com um bloco tool_use escolhendo um destino."""
    bloco = MagicMock()
    bloco.type = "tool_use"
    bloco.name = "rotear"
    bloco.input = {"especialista": destino}
    resposta = MagicMock()
    resposta.content = [bloco]
    return resposta


def _mock_supervisor_client(destino: str, partes: list[str]) -> MagicMock:
    """Client com roteamento (create) e resposta em streaming (stream)."""
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_resp_tool_use(destino))
    client.messages.stream = MagicMock(return_value=_FakeStream(partes))
    client.close = AsyncMock()
    return client


def test_listar_agentes(client: TestClient) -> None:
    response = client.get("/api/agentes")
    assert response.status_code == 200
    corpo = response.json()
    assert {a["slug"] for a in corpo} == AGENTES_ESPERADOS
    assert corpo[0]["slug"] == "supervisor"  # primeiro contato
    for agente in corpo:
        assert agente["nome"]
        assert agente["descricao"]


def test_card_direto_nao_roteia(client: TestClient) -> None:
    """Clique num card (slug de especialista) faz stream direto, sem chamar roteamento."""
    fake = _mock_anthropic_stream(["Excelência, ", "segue a petição."])
    client.app.state.anthropic = fake
    response = client.post(
        "/api/chat",
        json={"agente": "peticoes", "mensagens": [{"role": "user", "content": "Petição de cobrança"}]},
    )
    assert response.status_code == 200
    assert response.text == "Excelência, segue a petição."
    fake.messages.create.assert_not_called()
    assert "condominial" in fake.messages.stream.call_args.kwargs["system"].lower()


def test_supervisor_roteia_para_especialista(client: TestClient) -> None:
    """Mensagem ao supervisor é roteada (tool use) e a resposta do especialista é transmitida."""
    fake = _mock_supervisor_client("notificacoes", ["Notificação: ", "prezado condômino."])
    client.app.state.anthropic = fake
    response = client.post(
        "/api/chat",
        json={"agente": "supervisor", "mensagens": [{"role": "user", "content": "cão sujou o elevador"}]},
    )
    assert response.status_code == 200
    assert response.text == "Notificação: prezado condômino."
    fake.messages.create.assert_awaited_once()
    assert "notifica" in fake.messages.stream.call_args.kwargs["system"].lower()


def test_supervisor_trata_onboarding_diretamente(client: TestClient) -> None:
    """Se o roteamento devolve 'supervisor', a própria persona do supervisor responde."""
    fake = _mock_supervisor_client("supervisor", ["Olá! ", "vamos começar o onboarding."])
    client.app.state.anthropic = fake
    response = client.post(
        "/api/chat",
        json={"agente": "supervisor", "mensagens": [{"role": "user", "content": "oi"}]},
    )
    assert response.status_code == 200
    assert response.text == "Olá! vamos começar o onboarding."
    assert "onboarding" in fake.messages.stream.call_args.kwargs["system"].lower()
```

Manter os testes existentes que continuam válidos: `test_chat_aceita_modelo_economico` (trocar agente para `peticoes`), `test_chat_agente_desconhecido_retorna_404`, `test_chat_sem_mensagens_retorna_422`, `test_chat_modelo_invalido_retorna_422`, `test_index_serve_interface`, `test_proposta_acessivel_externamente`, `test_chat_bloqueado_para_host_externo`, `test_index_bloqueado_para_host_externo`. Remover `test_chat_retorna_resposta_em_streaming` (substituído por `test_card_direto_nao_roteia`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat.py -v`
Expected: FAIL (ex.: `AGENTES_ESPERADOS` != registro atual; `agente_existe`/nova assinatura ausentes)

- [ ] **Step 3: Write minimal implementation**

Reescrever `app/services/chat.py`:

```python
"""Lógica de negócio do chat: registro de agentes, roteamento e streaming."""

from collections.abc import AsyncIterator
from typing import cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

from app.agents.base import BaseAgent
from app.agents.consulta_historica import ConsultaHistoricaAgent
from app.agents.contratos import ContratosAgent
from app.agents.juridico_geral import JuridicoGeralAgent
from app.agents.notificacoes import NotificacoesAgent
from app.agents.pareceres import PareceresAgent
from app.agents.peticoes import PeticoesAgent
from app.agents.supervisor import SupervisorAgent
from app.schemas.chat import AgenteInfo, ChatRequest

_REGISTRO: dict[str, tuple[type[BaseAgent], AgenteInfo]] = {
    "supervisor": (
        SupervisorAgent,
        AgenteInfo(
            slug="supervisor",
            nome="Supervisor",
            descricao="Primeiro contato, onboarding do escritório e encaminhamento",
            icone="compass",
        ),
    ),
    "notificacoes": (
        NotificacoesAgent,
        AgenteInfo(
            slug="notificacoes",
            nome="Notificações",
            descricao="Notificações a condôminos a partir de um comando simples",
            icone="bell",
        ),
    ),
    "peticoes": (
        PeticoesAgent,
        AgenteInfo(
            slug="peticoes",
            nome="Petições",
            descricao="Peças do contencioso condominial (cobrança de cotas, execução)",
            icone="file-text",
        ),
    ),
    "contratos": (
        ContratosAgent,
        AgenteInfo(
            slug="contratos",
            nome="Contratos",
            descricao="Minutas, análise de risco, vencimento e rescisão",
            icone="signature",
        ),
    ),
    "pareceres": (
        PareceresAgent,
        AgenteInfo(
            slug="pareceres",
            nome="Pareceres",
            descricao="Pareceres jurídicos condominiais fundamentados",
            icone="scroll",
        ),
    ),
    "consulta-historica": (
        ConsultaHistoricaAgent,
        AgenteInfo(
            slug="consulta-historica",
            nome="Consulta Histórica",
            descricao="Síndico atual, reajustes, deliberações e atas do acervo",
            icone="history",
        ),
    ),
    "juridico-geral": (
        JuridicoGeralAgent,
        AgenteInfo(
            slug="juridico-geral",
            nome="Jurídico Geral",
            descricao="Dúvidas de direito condominial com fundamentação",
            icone="scale",
        ),
    ),
}

MODELO_ROTEAMENTO = "claude-haiku-4-5-20251001"

_ROTEAVEIS = [s for s in _REGISTRO if s != "supervisor"]

_ROTEAR_TOOL = {
    "name": "rotear",
    "description": (
        "Encaminha a demanda do usuário ao especialista adequado, ou mantém com o "
        "Supervisor para onboarding e conversa geral."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "especialista": {
                "type": "string",
                "enum": [*_ROTEAVEIS, "supervisor"],
                "description": (
                    "slug do especialista: 'notificacoes', 'peticoes', 'contratos', "
                    "'pareceres', 'consulta-historica', 'juridico-geral'; ou 'supervisor' "
                    "para saudação, onboarding ou dúvida sobre a plataforma."
                ),
            }
        },
        "required": ["especialista"],
    },
}

ROTEAMENTO_PROMPT = """Você roteia a mensagem de um hub jurídico condominial para o especialista \
adequado. Analise o histórico e a última mensagem e escolha UM destino chamando a ferramenta \
'rotear'. Use 'notificacoes' para pedidos de notificação a condômino/unidade; 'peticoes' para \
peças processuais (cobrança de cotas, execução, ações); 'contratos' para elaboração/revisão de \
contrato, vencimento ou rescisão; 'pareceres' para pareceres fundamentados; 'consulta-historica' \
para perguntas factuais do acervo (síndico atual, reajuste, deliberações, atas); 'juridico-geral' \
para dúvidas jurídicas gerais de direito condominial; 'supervisor' para saudações, onboarding, \
dúvidas sobre a plataforma ou quando não estiver claro."""


def listar_agentes() -> list[AgenteInfo]:
    """Retorna os metadados de todos os agentes disponíveis no hub."""
    return [info for _, info in _REGISTRO.values()]


def agente_existe(slug: str) -> bool:
    """Indica se o slug corresponde a um agente registrado."""
    return slug in _REGISTRO


def obter_agente(slug: str, client: AsyncAnthropic) -> BaseAgent | None:
    """Instancia o agente correspondente ao slug, ou None se não existir.

    Args:
        slug: Identificador do agente (ex: "peticoes").
        client: Cliente Anthropic compartilhado da aplicação.

    Returns:
        Instância do agente ou None quando o slug é desconhecido.
    """
    entrada = _REGISTRO.get(slug)
    if entrada is None:
        return None
    classe, _ = entrada
    return classe(client)


async def escolher_especialista(
    client: AsyncAnthropic, mensagens: list[MessageParam]
) -> str:
    """Decide, via tool use, para qual agente encaminhar a conversa.

    Args:
        client: Cliente Anthropic compartilhado.
        mensagens: Histórico completo da conversa.

    Returns:
        Slug do agente escolhido; "supervisor" como padrão seguro.
    """
    resposta = await client.messages.create(
        model=MODELO_ROTEAMENTO,
        max_tokens=512,
        system=ROTEAMENTO_PROMPT,
        messages=mensagens,
        tools=[_ROTEAR_TOOL],
        tool_choice={"type": "tool", "name": "rotear"},
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use" and bloco.name == "rotear":
            slug = bloco.input.get("especialista", "supervisor")
            return slug if slug in _REGISTRO else "supervisor"
    return "supervisor"


async def gerar_resposta_stream(
    payload: ChatRequest, client: AsyncAnthropic
) -> AsyncIterator[str]:
    """Gera a resposta em streaming, roteando quando o alvo é o Supervisor.

    Args:
        payload: Requisição validada com agente, histórico e modelo.
        client: Cliente Anthropic compartilhado.

    Yields:
        Trechos de texto da resposta do agente que efetivamente atende.
    """
    mensagens = cast(
        list[MessageParam],
        [{"role": m.role, "content": m.content} for m in payload.mensagens],
    )
    slug = payload.agente
    if slug == "supervisor":
        slug = await escolher_especialista(client, mensagens)
    agente = obter_agente(slug, client) or obter_agente("supervisor", client)
    assert agente is not None  # supervisor está sempre registrado
    async for trecho in agente.responder_stream(mensagens, modelo=payload.modelo):
        yield trecho
```

Atualizar `app/routers/chat.py`:

```python
"""Router do chat com os agentes do hub."""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.schemas.chat import AgenteInfo, ChatRequest
from app.services import chat as chat_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/agentes", response_model=list[AgenteInfo], status_code=200)
async def listar_agentes() -> list[AgenteInfo]:
    """Lista os agentes especialistas disponíveis no hub."""
    return chat_service.listar_agentes()


@router.post("/chat", status_code=200)
async def conversar(payload: ChatRequest, request: Request) -> StreamingResponse:
    """Envia o histórico ao agente escolhido (ou roteia via Supervisor) em streaming."""
    if not chat_service.agente_existe(payload.agente):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente desconhecido: {payload.agente}",
        )
    return StreamingResponse(
        chat_service.gerar_resposta_stream(payload, request.app.state.anthropic),
        media_type="text/plain; charset=utf-8",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chat.py -v`
Expected: PASS (todos, incluindo os 3 novos de roteamento)

- [ ] **Step 5: Commit**

```bash
git add app/services/chat.py app/routers/chat.py tests/test_chat.py
git commit -m "feat: registro dos 7 agentes e roteamento híbrido por tool use"
```

---

### Task 4: Front re-tematizado para o escritório

Faz o Supervisor ser o agente padrão (primeiro contato), adiciona ícones/exemplos dos novos agentes e insere os placeholders inertes de seletor de cliente e status Google.

**Files:**
- Modify: `app/static/index.html` (mapa `ICONES`, `EXEMPLOS`, `agenteAtual`, copy de onboarding, placeholders inertes)
- Test: `tests/test_chat.py` (asserção de que o front serve os placeholders)

**Interfaces:**
- Consumes: `/api/agentes` (7 agentes, supervisor primeiro — Task 3).
- Produces: nenhum símbolo Python novo; contrato = HTML servido em `/` contém os textos-âncora testados.

- [ ] **Step 1: Write the failing test** (adicionar em `tests/test_chat.py`)

```python
def test_index_tem_placeholders_do_escritorio(client: TestClient) -> None:
    """O front expõe os placeholders inertes de cliente e conexão Google."""
    html = client.get("/").text
    assert "Condomínio ativo" in html
    assert "Google Drive" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat.py::test_index_tem_placeholders_do_escritorio -v`
Expected: FAIL com `AssertionError` (textos ainda não existem no HTML)

- [ ] **Step 3: Write minimal implementation**

Em `app/static/index.html`:

1. No objeto `ICONES` (após a entrada `signature`), acrescentar quatro ícones:

```javascript
  ,compass: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>',
  bell: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
  scroll: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0 0 4h3z"/><path d="M19 17V5a2 2 0 0 0-2-2H8v14"/><path d="M16 21H6a2 2 0 0 1-2-2v-2h12v2a2 2 0 0 0 2 2z"/></svg>',
  history: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/></svg>'
```

2. Substituir `EXEMPLOS` pelos exemplos condominiais:

```javascript
const EXEMPLOS = {
  'supervisor': 'Olá! Sou novo aqui — como funciona a plataforma?',
  'notificacoes': 'Gere uma notificação: cão fez sujeira na área comum do Bloco B, unidade 34',
  'peticoes': 'Redija uma petição de cobrança de cotas condominiais em atraso',
  'contratos': 'Revise os riscos de um contrato de portaria e prepare a minuta de rescisão',
  'pareceres': 'Elabore um parecer sobre a validade de multa aplicada sem prévia notificação',
  'consulta-historica': 'Quando foi o último reajuste da taxa condominial deste condomínio?',
  'juridico-geral': 'Qual o quórum para alteração da convenção de condomínio?'
};
```

3. Trocar o agente padrão para o Supervisor:

```javascript
let agenteAtual = 'supervisor';
```

4. Ajustar a saudação da tela inicial. Localizar o `<h2 id="agent-title-empty">` / heading "Como posso ajudar, doutor(a)?" e o subtítulo, substituindo o subtítulo por copy do escritório (mantendo os ids existentes):

```html
<p class="empty-sub">Comece pelo <b>Supervisor</b> para o onboarding, ou escolha um especialista do escritório.</p>
```

5. No topo da sidebar, logo após o bloco `.brand`, inserir os placeholders inertes:

```html
<div class="ctx-box">
  <label class="ctx-label">Condomínio ativo</label>
  <select class="ctx-select" disabled title="Disponível quando o acervo estiver conectado (M2/M3)">
    <option>— nenhum conectado —</option>
  </select>
  <div class="ctx-google" title="Conexão com o Google Drive chega na fase das Mãos (M3)">
    <span class="dot-off"></span> Google Drive: desconectado
  </div>
</div>
```

6. Adicionar os estilos no bloco `<style>` (perto das regras de `.brand`):

```css
.ctx-box { padding: 10px 12px; margin: 0 6px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; display: flex; flex-direction: column; gap: 8px; }
.ctx-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-dim); }
.ctx-select { width: 100%; background: var(--panel-3); color: var(--text-dim); border: 1px solid var(--border); border-radius: 8px; padding: 7px 8px; font-size: 0.8rem; }
.ctx-google { font-size: 0.75rem; color: var(--text-dim); display: flex; align-items: center; gap: 6px; }
.dot-off { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); display: inline-block; }
```

(Se o heading/subtítulo tiverem ids diferentes dos citados, preservar os ids reais e alterar apenas o texto; o essencial testável é que "Condomínio ativo" e "Google Drive" apareçam no HTML.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chat.py::test_index_tem_placeholders_do_escritorio -v`
Expected: PASS

- [ ] **Step 5: Verificação visual no navegador**

Subir o preview (`preview_start` com `lexhub`), abrir `/`, confirmar: Supervisor é o card ativo por padrão; 7 cards aparecem com ícones; a caixa "Condomínio ativo" e "Google Drive: desconectado" estão na sidebar (inertes). Ajustar CSS se algo quebrar o layout.

- [ ] **Step 6: Commit**

```bash
git add app/static/index.html tests/test_chat.py
git commit -m "feat: front re-tematizado do escritório com supervisor padrão e placeholders inertes"
```

---

### Task 5: Verificação final — suíte verde + lint

**Files:**
- Modify: (apenas correções pontuais se algo falhar)

- [ ] **Step 1: Rodar a suíte completa**

Run: `uv run pytest -q`
Expected: todos passando (incluindo `tests/test_agentes_condominiais.py` e `tests/test_chat.py`). Nenhuma referência a `processos` remanescente.

- [ ] **Step 2: Lint e formatação**

Run: `uv run ruff check app/ tests/` — Expected: sem erros.
Run: `uv run black --check app/ tests/` — Expected: já formatado (senão rodar `uv run black app/ tests/`).

- [ ] **Step 3: Verificação de tipos (best-effort do projeto)**

Run: `uv run pyright app/services/chat.py app/agents/` (se o projeto usar pyright) — corrigir tipagens apontadas.

- [ ] **Step 4: Commit de fechamento (se houve ajustes)**

```bash
git add -A
git commit -m "chore: fecha M1 (cérebro) com suíte verde e lint limpo"
```

---

## Notas de handoff para M2+

- Gancho de memória do cliente: o método `responder_stream` dos especialistas ganhará, na M4, um
  parâmetro de contexto do cliente (documentos/histórico). Na M1 os prompts já sinalizam "quando a
  conexão ao acervo estiver ativa" — nenhum código morto foi adicionado.
- O seletor "Condomínio ativo" e o status "Google Drive" do front são inertes na M1; passam a ser
  alimentados por `/api/condominios` (M2) e pelo status OAuth (M3).
- O roteamento usa `MODELO_ROTEAMENTO` (Haiku) fixo para baixo custo/latência; a resposta final usa o
  modelo escolhido pelo usuário.
