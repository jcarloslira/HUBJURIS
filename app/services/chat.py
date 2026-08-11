"""Lógica de negócio do chat: registro de agentes, roteamento e streaming."""

from collections.abc import AsyncIterator, Awaitable, Callable
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
from app.schemas.agentes import AgenteConfig
from app.schemas.chat import AgenteInfo, ChatRequest
from app.services.anexos import construir_blocos
from app.services.modelos import LeitorDrive, carregar_modelos, formatar_referencia

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
dúvidas sobre a plataforma, para CADASTRAR/ORGANIZAR condomínios (projetos) ou registrar fatos na \
memória de um condomínio, ou quando não estiver claro.

REGRA DECISIVA: se a mensagem contém uma tarefa jurídica clara, roteie para o especialista MESMO \
que ela venha junto de uma saudação ("boa noite, preciso de uma notificação" → 'notificacoes'). \
Uma saudação sozinha não é motivo para ficar no 'supervisor' se há tarefa identificável. Mantenha \
no destino atual quando o usuário está apenas continuando/complementando a mesma tarefa."""


INSTRUCAO_OPCOES = """Quando for útil oferecer escolhas ao usuário (onboarding, decisões, \
próximos passos), apresente-as como um bloco de opções clicáveis, EXATAMENTE neste formato:
[[OPCOES multipla=nao outros=sim]]
Sua pergunta numa linha só
- Primeira opção
- Segunda opção
- Terceira opção
[[/OPCOES]]
Regras: escreva uma frase curta ANTES do bloco; `multipla=sim` permite marcar várias; `outros=sim` \
deixa o usuário digitar uma resposta livre.
DISCIPLINA (importante): use no MÁXIMO um bloco por resposta e só quando um conjunto FECHADO de \
opções realmente decide o rumo (ex.: o motivo da notificação). NUNCA use opções para coletar \
dados abertos e específicos (nome do condomínio, número da unidade, datas, nomes de pessoas) — \
esses você pergunta em texto normal OU já deixa como placeholder no rascunho. Prefira AGIR: se dá \
para adiantar o trabalho com placeholders, faça isso em vez de abrir outra rodada de perguntas."""

INSTRUCAO_ACOES = """Você pode EXECUTAR ações nos conectores do escritório (Google Agenda, Gmail, \
Google Docs, Google Sheets). REGRA DE OURO para ações externas: NUNCA execute direto. Primeiro \
RESUMA o que fará (ex.: "vou criar o evento 'Assembleia' em 05/08 às 19h") e peça CONFIRMAÇÃO com \
um bloco [[OPCOES outros=sim]] contendo "Confirmar" e "Cancelar". Só chame a ferramenta DEPOIS que \
o usuário confirmar. E-mails saem como RASCUNHO (o usuário revisa e envia). Se um conector não \
estiver conectado, oriente a conectar em Configurações → Conectores."""

INSTRUCAO_ENTREGA = """Sobre o acervo do escritório e a entrega da peça:
- Se você recebeu acima modelos do escritório ou trechos de conhecimento recuperado, baseie a peça \
no padrão e no estilo deles — é o jeito da casa.
- Se não houver modelos do escritório (Drive não conectado ou pasta do acervo não escolhida), você \
AINDA produz a peça completa com placeholders. Ao final, UMA vez só (sem repetir a cada turno), \
ofereça de forma útil: (a) que o usuário pode colar/enviar uma peça de EXEMPLO para você seguir \
exatamente o padrão do escritório; e (b) que, conectando o Google Drive em Configurações → \
Conectores, você passa a se basear no acervo real (histórico de peças daquele condomínio/unidade).
- Ao concluir qualquer peça (notificação, petição, contrato, parecer), lembre em UMA linha que o \
usuário pode baixá-la em Word ou PDF pelo botão "Exportar" na própria resposta.
- Se o usuário pedir para "seguir o mesmo padrão/identidade" de um documento que enviou, ou para \
reaproveitar a última peça de uma unidade/condomínio, trate esse material como referência fiel de \
layout e linguagem."""


def listar_agentes() -> list[AgenteInfo]:
    """Retorna os metadados de todos os agentes disponíveis no hub."""
    return [info for _, info in _REGISTRO.values()]


def configs_padrao() -> list[AgenteConfig]:
    """Config padrão de cada agente vinda do código (semente da tabela)."""
    padroes: list[AgenteConfig] = []
    for ordem, (slug, (classe, info)) in enumerate(_REGISTRO.items()):
        padroes.append(
            AgenteConfig(
                slug=slug,
                nome=info.nome,
                descricao=info.descricao,
                icone=info.icone,
                system_prompt=classe.system_prompt,
                modelo=classe.model,
                max_tokens=classe.max_tokens,
                ativo=True,
                ordem=ordem,
            )
        )
    return padroes


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


async def escolher_especialista(client: AsyncAnthropic, mensagens: list[MessageParam]) -> str:
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
    payload: ChatRequest,
    client: AsyncAnthropic,
    *,
    conector: LeitorDrive | None = None,
    acervo_raiz: str | None = None,
    on_usage: Callable[[str, str, int, int], Awaitable[None]] | None = None,
    ferramentas: list[dict] | None = None,
    executar_ferramenta: Callable[[str, dict], Awaitable[str]] | None = None,
    configs: dict[str, AgenteConfig] | None = None,
    buscar_conhecimento: Callable[[str], Awaitable[str]] | None = None,
) -> AsyncIterator[str]:
    """Gera a resposta em streaming, roteando quando o alvo é o Supervisor.

    Quando um conector de Drive e a pasta-raiz do acervo são informados, o
    especialista escolhido é "aterrado" nos modelos do escritório (produz no
    padrão do escritório). Falha na leitura do Drive degrada graciosamente: o
    agente responde mesmo sem os modelos.

    Args:
        payload: Requisição validada com agente, histórico e modelo.
        client: Cliente Anthropic compartilhado.
        conector: Leitor do Drive do escritório (opcional).
        acervo_raiz: Pasta-raiz do acervo de modelos (opcional).
        on_usage: Callback opcional (agente, modelo, tokens_in, tokens_out)
            com o consumo real medido pela API.

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
        # Sentinela de hand-off: informa ao frontend qual especialista assumiu,
        # para a interface mostrar a troca (o cliente remove esta marca do texto).
        yield f"[[AGENTE:{slug}]]"
    agente = obter_agente(slug, client) or obter_agente("supervisor", client)
    assert agente is not None  # supervisor está sempre registrado

    # Config do banco (editável sem redeploy) sobrepõe os padrões do código.
    if configs and slug in configs:
        cfg = configs[slug]
        agente.system_prompt = cfg.system_prompt
        agente.model = cfg.modelo
        agente.max_tokens = cfg.max_tokens

    # Anexos entram só na resposta do especialista (roteamento fica no texto,
    # mais barato): a última mensagem do usuário vira texto + blocos de arquivo.
    mensagens_agente = mensagens
    if payload.anexos:
        ultima = payload.mensagens[-1]
        blocos = construir_blocos(ultima.content, payload.anexos)
        mensagens_agente = cast(
            list[MessageParam],
            [*mensagens[:-1], {"role": ultima.role, "content": blocos}],
        )

    referencia = ""
    if conector is not None and acervo_raiz:
        try:
            modelos = await carregar_modelos(conector, acervo_raiz, slug, limite=2)
            referencia = formatar_referencia(modelos)
        except Exception:  # noqa: BLE001 - Drive indisponível não impede a resposta
            referencia = ""

    # Busca na base de conhecimento (RAG): trechos da legislação, protocolos e do
    # acervo do escritório relevantes à última mensagem. Falha não impede a resposta.
    if buscar_conhecimento is not None:
        ultima_user = next(
            (m.content for m in reversed(payload.mensagens) if m.role == "user"), ""
        )
        try:
            bloco = await buscar_conhecimento(ultima_user)
        except Exception:  # noqa: BLE001 - base indisponível degrada graciosamente
            bloco = ""
        if bloco:
            referencia = f"{referencia}\n\n{bloco}" if referencia else bloco

    if payload.anexos:
        nota = (
            "O usuário anexou arquivo(s) a esta mensagem e o conteúdo foi incluído junto "
            "(como texto extraído, imagem ou PDF). Trate esse conteúdo como recebido e use-o "
            "diretamente na resposta; NUNCA diga que não consegue acessar, abrir ou ler anexos."
        )
        referencia = f"{referencia}\n\n{nota}" if referencia else nota

    referencia = f"{referencia}\n\n{INSTRUCAO_OPCOES}" if referencia else INSTRUCAO_OPCOES
    if slug == "supervisor":
        referencia = f"{referencia}\n\n{INSTRUCAO_ACOES}"
    else:
        # Especialistas redigem peças: orientação de acervo (Drive/exemplo) e entrega (export).
        referencia = f"{referencia}\n\n{INSTRUCAO_ENTREGA}"

    registrar = None
    if on_usage is not None:
        slug_final = slug
        modelo_final = payload.modelo or agente.model

        async def registrar(tokens_in: int, tokens_out: int) -> None:
            await on_usage(slug_final, modelo_final, tokens_in, tokens_out)

    # As ferramentas de sistema (cadastrar condomínio, memória...) ficam com o
    # Supervisor — o maestro que conduz onboarding e organização. Especialistas
    # seguem focados na peça que produzem.
    usa_ferramentas = slug == "supervisor" and executar_ferramenta is not None
    async for trecho in agente.responder_stream(
        mensagens_agente,
        modelo=payload.modelo,
        referencia=referencia,
        on_usage=registrar,
        ferramentas=ferramentas if usa_ferramentas else None,
        executar_ferramenta=executar_ferramenta if usa_ferramentas else None,
    ):
        yield trecho
