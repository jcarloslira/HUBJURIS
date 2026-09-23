"""Ferramentas de aprendizado — o agente guarda a ordem do escritório e obedece sempre.

O advogado corrige uma vez. Se a correção morre no fim da conversa, ele corrige
de novo amanhã, e o Hub vira um estagiário que nunca aprende. Com estas três
ferramentas a lição fica: ``aprender`` grava, ``aprendizados`` mostra o que já foi
aprendido e ``esquecer_regra`` desfaz quando o escritório mudar de ideia.

O que é gravado aqui entra no prompt de TODOS os agentes daquele escritório, em
toda conversa seguinte — por isso a regra tem de ser curta, imperativa e valer
para o trabalho, não para um caso só.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.aprendizado import ESCOPOS, AprendizadoService

Handler = Callable[[dict[str, Any]], Awaitable[str]]

FERRAMENTAS_APRENDIZADO: list[dict[str, Any]] = [
    {
        "name": "aprender",
        "description": (
            "Grava PARA SEMPRE uma regra de como este escritório quer o trabalho feito. "
            "Use SEMPRE que o usuário: corrigir você ('não é assim', 'o certo é'), impor "
            "um padrão ('sempre assine com a OAB de quem gerou', 'nunca ponha seção de "
            "agenda'), dizer uma preferência de estilo, ou mandar anotar/memorizar algo. "
            "A regra passa a valer em TODAS as conversas futuras, com qualquer agente. "
            "NÃO use para dado de um condomínio (isso é hub_atualizar_condominio ou "
            "hub_anotar) nem para pedido pontual desta conversa. Depois de gravar, "
            "confirme ao usuário em uma linha o que você aprendeu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "regra": {
                    "type": "string",
                    "description": (
                        "A regra no imperativo, completa e autoexplicativa — ela será lida "
                        "meses depois, fora desta conversa. Ex.: 'Em relatório ao síndico, "
                        "nunca criar seção de agenda ou de prazos futuros; o compromisso "
                        "entra no Próximo passo do próprio item.'"
                    ),
                },
                "escopo": {
                    "type": "string",
                    "enum": sorted(ESCOPOS),
                    "description": (
                        "Onde a regra vale: 'geral' (toda resposta), 'relatorio' (relatórios "
                        "ao cliente) ou o agente específico. Na dúvida, 'geral'."
                    ),
                },
                "motivo": {
                    "type": "string",
                    "description": "Por que o escritório quer assim, se o usuário explicou.",
                },
            },
            "required": ["regra"],
        },
    },
    {
        "name": "aprendizados",
        "description": (
            "Lista as regras que este escritório já te ensinou. Use quando o usuário "
            "perguntar o que você aprendeu, o que sabe sobre o padrão da casa, ou antes "
            "de esquecer alguma."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "esquecer_regra",
        "description": (
            "Desativa uma regra aprendida, quando o usuário disser que ela não vale mais "
            "('pode esquecer aquilo de…', 'mudei de ideia', 'agora é o contrário'). "
            "Informe ao usuário qual regra saiu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "busca": {
                    "type": "string",
                    "description": "Trecho da regra a desativar (ex.: 'seção de agenda').",
                }
            },
            "required": ["busca"],
        },
    },
]

NOMES_APRENDIZADO = {f["name"] for f in FERRAMENTAS_APRENDIZADO}

INSTRUCAO_APRENDIZADO = """APRENDIZADO — você aprende com este escritório e não \
esquece:
- Quando o usuário corrigir você, impor um padrão ou dizer "sempre/nunca/de agora em \
diante/da próxima vez faça assim", chame `aprender` na hora, ANTES de continuar a \
tarefa, e confirme numa linha ("Anotado: daqui em diante…"). Não espere ele mandar \
salvar — ele não sabe que precisa.
- Uma correção vale para a CLASSE de trabalho, não só para o documento da vez: se ele \
reprovou uma seção do relatório, a regra é para todo relatório.
- Grave a regra do jeito que ela terá de ser lida daqui a seis meses, por outro agente, \
sem esta conversa por perto: imperativa, completa, sem "como combinamos".
- Se ele disser que uma regra não vale mais, chame `esquecer_regra`. Nunca discuta a \
ordem: o padrão é dele.
- Perguntou o que você aprendeu? `aprendizados` e uma lista honesta. Nunca invente \
regra que não está lá."""


def montar_handlers_aprendizado(
    servico: AprendizadoService, escritorio_id: str, user_id: str | None = None
) -> dict[str, Handler]:
    """Handlers de aprendizado, presos ao escritório do usuário logado."""

    async def aprender(entrada: dict[str, Any]) -> str:
        regra = str(entrada.get("regra") or "")
        gravada = await servico.aprender(
            escritorio_id,
            regra,
            escopo=str(entrada.get("escopo") or "geral"),
            motivo=entrada.get("motivo"),
            origem="ferramenta",
            criado_por=user_id,
        )
        if gravada is None:
            return (
                "Essa regra já estava aprendida (ou veio curta demais para valer). "
                "Confirme ao usuário que o padrão já está valendo, sem repetir o registro."
            )
        return (
            f"Aprendido e valendo em todas as conversas deste escritório: {gravada}\n"
            "Confirme ao usuário em UMA linha e siga com a tarefa."
        )

    async def listar(_: dict[str, Any]) -> str:
        regras = await servico.listar(escritorio_id)
        if not regras:
            return (
                "Este escritório ainda não te ensinou nenhuma regra própria. Diga isso com "
                "franqueza e convide: basta corrigir ou dizer o padrão uma vez que você passa "
                "a seguir sempre."
            )
        linhas = [
            f"- [{r['escopo']}] {r['regra']}" for r in reversed(regras)
        ]
        return f"Regras aprendidas com este escritório ({len(regras)}):\n" + "\n".join(linhas)

    async def esquecer(entrada: dict[str, Any]) -> str:
        saidas = await servico.esquecer(escritorio_id, str(entrada.get("busca") or ""))
        if not saidas:
            return "Nenhuma regra aprendida bate com isso. Peça ao usuário para indicar qual."
        return "Regras desativadas (não valem mais):\n" + "\n".join(f"- {s}" for s in saidas)

    return {
        "aprender": aprender,
        "aprendizados": listar,
        "esquecer_regra": esquecer,
    }
