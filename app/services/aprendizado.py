"""O que o escritório ensinou ao agente — e que passa a valer sozinho.

O Dr. Wilker corrige uma vez ("não ponha seção de agenda", "assine sempre com a
OAB de quem gerou o relatório") e a correção tem de valer para sempre, em
qualquer conversa, sem ninguém repetir. É isso que esta classe guarda.

Diferença para as outras memórias do Hub:

- ``diretrizes`` (016) é o dossiê do escritório, carregado de uma vez por fora;
- ``condominio_fatos`` é o que se sabe de um CONDOMÍNIO;
- ``interacoes`` é onde cada DEMANDA parou;
- **aprendizados** é como o escritório quer o TRABALHO FEITO. Entra no prompt de
  todo agente e, em conflito, ganha do padrão da casa.

Duas portas de entrada, as duas automáticas do ponto de vista do usuário: a
ferramenta ``aprender`` (o agente reconhece a ordem na hora) e o extrator de
memória (relê o turno e captura a regra que passou batido).
"""

import re
from datetime import UTC, datetime
from typing import Any

from supabase import AsyncClient

# Quantas regras entram no prompt. Passou disso, o escritório tem de podar — e
# regra demais deixa de ser regra.
_MAX_NO_PROMPT = 40
_MAX_GUARDADAS = 120
_TAMANHO_MINIMO = 10
_TAMANHO_MAXIMO = 400

# Escopos válidos: 'geral' + os agentes + 'relatorio' (que atravessa agentes).
ESCOPOS = {
    "geral",
    "relatorio",
    "notificacoes",
    "peticoes",
    "contratos",
    "pareceres",
    "consulta-historica",
    "juridico-geral",
}

# O usuário raramente diz "aprenda isto": ele corrige. Estas marcas denunciam uma
# ordem durável no meio de um pedido comum e ligam o extrator mesmo em turno curto.
_MARCAS_DE_ORDEM = (
    "sempre",
    "nunca",
    "jamais",
    "de agora em diante",
    "daqui em diante",
    "daqui pra frente",
    "daqui para frente",
    "a partir de agora",
    "da proxima vez",
    "proxima vez",
    "nao faca",
    "nao coloque",
    "nao ponha",
    "nao use",
    "nao gosto",
    "nao quero",
    "prefiro",
    "padrao do escritorio",
    "padrao daqui",
    "regra do escritorio",
    "pode anotar",
    "anote isso",
    "memoriza",
    "memorize",
    "lembre disso",
    "guarde isso",
    "corrigindo",
    "o certo e",
    "nao e assim",
    "assim nao",
    "evite",
    "so use",
    "tem que ser",
    "tem de ser",
)


def _sem_acento(texto: str) -> str:
    tabela = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    return texto.lower().translate(tabela)


def parece_instrucao(mensagem: str) -> bool:
    """A mensagem carrega uma ordem durável ("nunca faça X", "prefiro Y")?

    Serve de gatilho barato: sem isto, um turno curto ("não ponha agenda" →
    "Certo.") nunca chegaria ao extrator e a lição se perderia.
    """
    texto = _sem_acento(mensagem)
    return any(marca in texto for marca in _MARCAS_DE_ORDEM)


def _chaves(regra: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9]+", _sem_acento(regra)) if len(p) > 3}


def mesma_regra(nova: str, antiga: str) -> bool:
    """Regra já ensinada, mesmo dita com outras palavras."""
    a, b = _chaves(nova), _chaves(antiga)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= 0.75


def _linha(regra: dict[str, Any]) -> str:
    """A regra como o agente a lê no prompt.

    O escopo vai na frente porque TODAS as regras entram no prompt: sem ele, uma
    regra de relatório pareceria valer também para uma notificação.
    """
    escopo = regra.get("escopo") or "geral"
    onde = "" if escopo == "geral" else f"(em {escopo}) "
    return f"- {onde}{regra['regra']}"


def _escopo_valido(escopo: Any) -> str:
    texto = str(escopo or "geral").strip().lower()
    return texto if texto in ESCOPOS else "geral"


class AprendizadoService:
    """Lê e grava as regras que o escritório ensinou ao agente."""

    def __init__(self, supabase: AsyncClient) -> None:
        self._db = supabase

    # ── Leitura ────────────────────────────────────────────────────────────

    async def listar(
        self, escritorio_id: str, *, escopo: str | None = None, incluir_inativas: bool = False
    ) -> list[dict[str, Any]]:
        consulta = (
            self._db.table("aprendizados")
            .select("id,escopo,regra,motivo,origem,ativo,vezes_aplicada,created_at")
            .eq("escritorio_id", escritorio_id)
        )
        if not incluir_inativas:
            consulta = consulta.eq("ativo", True)
        if escopo:
            consulta = consulta.in_("escopo", ["geral", escopo])
        result = await consulta.order("created_at", desc=True).limit(_MAX_GUARDADAS).execute()
        return list(result.data or [])

    async def bloco(self, escritorio_id: str, escopo: str | None = None) -> str:
        """As regras aprendidas, prontas para entrar no prompt."""
        regras = await self.listar(escritorio_id, escopo=escopo)
        if not regras:
            return ""
        # Mais antigas primeiro: a regra ensinada há meses é tão firme quanto a de ontem.
        linhas = [_linha(r) for r in reversed(regras[:_MAX_NO_PROMPT])]
        return (
            "O QUE ESTE ESCRITÓRIO JÁ TE ENSINOU — regras ditas pelo próprio escritório "
            "em conversas anteriores. Elas valem SEMPRE, sem ninguém precisar repetir, e "
            "PREVALECEM sobre o padrão geral em caso de conflito. Não pergunte se ainda "
            "valem; aplique:\n" + "\n".join(linhas)
        )

    # ── Escrita ────────────────────────────────────────────────────────────

    async def aprender(
        self,
        escritorio_id: str,
        regra: str,
        *,
        escopo: str = "geral",
        motivo: str | None = None,
        origem: str = "ferramenta",
        criado_por: str | None = None,
    ) -> str | None:
        """Grava a regra. Devolve o texto gravado, ou None se já era sabida.

        Regra repetida não vira linha nova: o prompt encheria de duplicata e a
        lição perderia força.
        """
        texto = " ".join(str(regra or "").split())[:_TAMANHO_MAXIMO]
        if len(texto) < _TAMANHO_MINIMO:
            return None
        conhecidas = await self.listar(escritorio_id)
        if any(mesma_regra(texto, r["regra"]) for r in conhecidas):
            return None
        await self._db.table("aprendizados").insert(
            {
                "escritorio_id": escritorio_id,
                "escopo": _escopo_valido(escopo),
                "regra": texto,
                "motivo": (motivo or None) and str(motivo)[:400],
                "origem": origem if origem in ("conversa", "ferramenta") else "ferramenta",
                "criado_por": criado_por,
                "ativo": True,
            }
        ).execute()
        return texto

    async def esquecer(self, escritorio_id: str, busca: str) -> list[str]:
        """Desativa as regras que batem com a busca. Devolve as que saíram.

        Desativa em vez de apagar: se o escritório mudar de ideia de novo, a
        conversa que ensinou continua rastreável.
        """
        alvo = " ".join(str(busca or "").split())
        if len(alvo) < 3:
            return []
        regras = await self.listar(escritorio_id)
        chave = _sem_acento(alvo)
        atingidas = [
            r
            for r in regras
            if chave in _sem_acento(r["regra"]) or mesma_regra(alvo, r["regra"])
        ]
        agora = datetime.now(UTC).isoformat()
        for regra in atingidas:
            await self._db.table("aprendizados").update(
                {"ativo": False, "atualizado_em": agora}
            ).eq("id", regra["id"]).eq("escritorio_id", escritorio_id).execute()
        return [r["regra"] for r in atingidas]
