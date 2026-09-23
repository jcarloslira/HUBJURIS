"""Memória viva do escritório — o que o agente já sabe antes de perguntar.

O Hub consulta EasyJur, Tiflux e Drive sob demanda, mas isso é *consulta*. O que
faltava era **memória**: lembrar o que o escritório pediu ontem, o que foi
entregue e onde cada demanda parou — inclusive em outra conversa, outro dia,
outro computador.

Duas metades, as duas automáticas:

- ``registrar``: depois de cada resposta, um modelo barato lê o par
  pergunta/resposta e grava assunto, onde parou, próximo passo e os fatos
  duráveis do condomínio. Ninguém precisa mandar salvar.
- ``contexto``: no começo de cada resposta, devolve as últimas demandas do
  escritório e a ficha do condomínio citado. O agente já começa sabendo.
"""

import json
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.services.aprendizado import AprendizadoService, parece_instrucao
from app.services.gestao import normalizar_nome
from supabase import AsyncClient

# Extrair memória é tarefa mecânica: modelo pequeno, barato e rápido.
MODELO_EXTRACAO = "claude-haiku-4-5-20251001"
_MAX_PEDIDO = 2_000
_MAX_RESPOSTA = 6_000
_MAX_TOKENS_EXTRACAO = 900
# Quanto da memória entra no prompt (o resto continua nas ferramentas hub_*).
_INTERACOES_ESCRITORIO = 10
_INTERACOES_CONDOMINIO = 6
_FATOS_CONDOMINIO = 20
_EVENTOS_CONDOMINIO = 6
# Um turno não pode despejar dezenas de "fatos" na memória do condomínio.
_MAX_FATOS_POR_TURNO = 3
# Nem virar um manual novo a cada conversa: regra demais deixa de ser regra.
_MAX_REGRAS_POR_TURNO = 2
# Resposta curta demais é saudação ou pedido de esclarecimento: nada a lembrar.
_MINIMO_PARA_LEMBRAR = 200
_PALAVRAS_IGNORADAS = {"condominio", "condominios", "cond", "residencial", "edificio"}

_PROMPT_EXTRACAO = """Você mantém a memória de um escritório de advocacia condominial.
Leia o pedido do usuário e a resposta do assistente e devolva APENAS um JSON:

{"condominio": "nome do condomínio tratado, ou null",
 "assunto": "o que foi tratado, em até 12 palavras",
 "onde_parou": "o estado em que a demanda ficou ao fim desta conversa, 1 frase",
 "proximo_passo": "a próxima ação concreta, ou null",
 "fatos": ["fato durável sobre o condomínio que valha lembrar daqui a meses"],
 "regras": [{"regra": "ordem durável sobre COMO o escritório quer o trabalho feito",
             "escopo": "geral|relatorio|notificacoes|peticoes|contratos|pareceres"}]}

Regras:
- "fatos" é para o que NÃO muda toda semana: síndico, administradora, convenção,
particularidade do condomínio, decisão estratégica do escritório. No máximo 3,
cada um numa frase curta e completa. Se nada for durável, devolva [].
- "regras" é o que o USUÁRIO ensinou sobre o MÉTODO e o ESTILO do escritório:
correção ("não é assim", "o certo é"), padrão imposto ("sempre assine com a OAB de
quem gerou", "nunca ponha seção de agenda"), preferência de forma, ordem de
memorizar. Escreva no imperativo, completa, como quem escreve um manual que será
lido daqui a seis meses SEM esta conversa por perto — nada de "como combinamos".
No máximo 2. Pedido pontual desta tarefa ("faça para o Ventura", "refaça com o
valor certo") NÃO é regra: devolva [].
- Não repita o conteúdo da peça nem transcreva jurisprudência.
- Não invente: só o que está no texto. Sem condomínio identificado, use null.
- Só o JSON, sem crases e sem comentário."""


def _tokens(nome: str) -> set[str]:
    """Palavras próprias de um nome (sem 'condomínio', 'residencial' e afins)."""
    return {
        t for t in normalizar_nome(nome).split() if t not in _PALAVRAS_IGNORADAS and len(t) > 2
    }


def fato_repetido(novo: str, antigo: str) -> bool:
    """Fato já registrado, mesmo reescrito com outras palavras."""
    ta, tb = set(normalizar_nome(novo).split()), set(normalizar_nome(antigo).split())
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.8


def _dia_br(iso: Any) -> str:
    texto = str(iso or "")[:10]
    return "/".join(reversed(texto.split("-"))) if texto.count("-") == 2 else texto


class MemoriaService:
    """Escreve e lê a memória do escritório entre conversas."""

    def __init__(self, supabase: AsyncClient, anthropic: AsyncAnthropic | None = None) -> None:
        self._db = supabase
        self._ia = anthropic
        self._aprendizado = AprendizadoService(supabase)

    # ── Leitura: o que entra no prompt ─────────────────────────────────────

    async def contexto(self, escritorio_id: str, mensagem: str) -> str:
        """Bloco de memória para o prompt: últimas demandas + ficha do condomínio citado."""
        partes: list[str] = []
        recentes = await self._interacoes(escritorio_id)
        if recentes:
            partes.append(
                "MEMÓRIA DO ESCRITÓRIO — últimas demandas (você se lembra disto de outras "
                "conversas; use sem perguntar de novo):\n"
                + "\n".join(self._linha_interacao(i) for i in recentes)
            )

        condominio = await self._condominio_citado(escritorio_id, mensagem)
        if condominio:
            partes.append(await self._ficha(escritorio_id, condominio))
        return "\n\n".join(p for p in partes if p)

    def _linha_interacao(self, interacao: dict[str, Any]) -> str:
        pedacos = [
            p
            for p in (
                _dia_br(interacao.get("created_at")),
                interacao.get("condominio_nome"),
                interacao.get("assunto"),
            )
            if p
        ]
        linha = " · ".join(str(p) for p in pedacos)
        if interacao.get("onde_parou"):
            linha += f" — parou em: {interacao['onde_parou']}"
        if interacao.get("proximo_passo"):
            linha += f" (próximo: {interacao['proximo_passo']})"
        return f"- {linha}"

    async def historico(
        self, escritorio_id: str, condominio_id: str | None = None
    ) -> list[dict[str, Any]]:
        """As últimas demandas (do escritório, ou de um condomínio) já com o nome."""
        return await self._interacoes(escritorio_id, condominio_id)

    async def _interacoes(
        self, escritorio_id: str, condominio_id: str | None = None
    ) -> list[dict[str, Any]]:
        limite = _INTERACOES_CONDOMINIO if condominio_id else _INTERACOES_ESCRITORIO
        consulta = (
            self._db.table("interacoes")
            .select("created_at,agente,assunto,onde_parou,proximo_passo,condominio_id")
            .eq("escritorio_id", escritorio_id)
        )
        if condominio_id:
            consulta = consulta.eq("condominio_id", condominio_id)
        result = await consulta.order("created_at", desc=True).limit(limite).execute()
        linhas = list(result.data or [])
        if not linhas:
            return []
        nomes = await self._nomes(escritorio_id)
        for linha in linhas:
            linha["condominio_nome"] = nomes.get(str(linha.get("condominio_id")))
        return linhas

    async def _nomes(self, escritorio_id: str) -> dict[str, str]:
        result = (
            await self._db.table("condominios")
            .select("id,nome")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        return {str(c["id"]): c["nome"] for c in (result.data or [])}

    async def _condominio_citado(
        self, escritorio_id: str, mensagem: str
    ) -> dict[str, Any] | None:
        """Acha na mensagem o condomínio de que se fala — sem o modelo pedir ferramenta."""
        alvo = _tokens(mensagem)
        if not alvo:
            return None
        result = (
            await self._db.table("condominios")
            .select("id,nome,cnpj,sindico,administradora,cidade,uf,observacoes")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        melhor: dict[str, Any] | None = None
        pontos = 0
        for condominio in result.data or []:
            nome = _tokens(condominio["nome"])
            comuns = nome & alvo if nome else set()
            # O nome próprio inteiro citado, ou pelo menos duas palavras dele.
            if comuns and (comuns == nome or len(comuns) >= 2) and len(comuns) > pontos:
                melhor, pontos = condominio, len(comuns)
        return melhor

    async def _ficha(self, escritorio_id: str, condominio: dict[str, Any]) -> str:
        cid = str(condominio["id"])
        linhas = [f"MEMÓRIA DO CONDOMÍNIO {condominio['nome']}"]
        cadastro = [f"{k}: {v}" for k, v in condominio.items() if k not in ("id", "nome") and v]
        if cadastro:
            linhas.append("Cadastro — " + " · ".join(cadastro))

        fatos = (
            await self._db.table("condominio_fatos")
            .select("fato")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", cid)
            .order("created_at", desc=True)
            .limit(_FATOS_CONDOMINIO)
            .execute()
        )
        if fatos.data:
            linhas.append("O que o escritório já sabe:")
            linhas += [f"- {f['fato']}" for f in fatos.data]

        historico = await self._interacoes(escritorio_id, cid)
        if historico:
            linhas.append("Demandas recentes deste condomínio:")
            linhas += [self._linha_interacao(i) for i in historico]

        eventos = (
            await self._db.table("eventos_condominio")
            .select("ocorrido_em,tipo,referencia,titulo")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", cid)
            .order("ocorrido_em", desc=True)
            .limit(_EVENTOS_CONDOMINIO)
            .execute()
        )
        if eventos.data:
            linhas.append("Últimos movimentos (EasyJur/Tiflux):")
            linhas += [
                f"- {_dia_br(e['ocorrido_em'])} · {e['tipo']} · "
                f"{e.get('referencia') or ''} {str(e.get('titulo') or '')[:120]}".strip()
                for e in eventos.data
            ]
        return "\n".join(linhas)

    # ── Escrita: a memória se atualiza sozinha ─────────────────────────────

    async def registrar(
        self,
        escritorio_id: str,
        *,
        user_id: str | None,
        agente: str,
        pedido: str,
        resposta: str,
    ) -> None:
        """Lê o turno que acabou e grava assunto, onde parou, fatos e regras aprendidas.

        A ordem do escritório costuma vir curta e sem cerimônia ("não põe seção de
        agenda"), respondida com um "certo". Por isso um pedido com cara de ordem
        liga o extrator mesmo quando a resposta é curta demais para virar demanda:
        a lição não pode depender do tamanho do texto.
        """
        if self._ia is None:
            return
        instrucao = parece_instrucao(pedido)
        if len(resposta.strip()) < _MINIMO_PARA_LEMBRAR and not instrucao:
            return
        extraido = await self._extrair(pedido, resposta)
        if not extraido:
            return
        await self._gravar_regras(escritorio_id, extraido.get("regras") or [], user_id)
        if len(resposta.strip()) < _MINIMO_PARA_LEMBRAR:
            return  # turno de ordem, sem demanda a registrar
        condominio = await self._condominio_por_nome(
            escritorio_id, str(extraido.get("condominio") or "")
        )
        await self._db.table("interacoes").insert(
            {
                "escritorio_id": escritorio_id,
                "user_id": user_id,
                "condominio_id": condominio,
                "agente": agente,
                "assunto": (extraido.get("assunto") or "")[:200] or None,
                "pedido": pedido[:1000],
                "resultado_resumo": (extraido.get("onde_parou") or "")[:1000] or None,
                "onde_parou": (extraido.get("onde_parou") or "")[:500] or None,
                "proximo_passo": (extraido.get("proximo_passo") or "")[:500] or None,
            }
        ).execute()
        if condominio:
            await self._gravar_fatos(escritorio_id, condominio, extraido.get("fatos") or [])

    async def _gravar_regras(
        self, escritorio_id: str, regras: list[Any], user_id: str | None
    ) -> None:
        """O que o escritório ensinou neste turno passa a valer em todas as conversas."""
        for item in regras[:_MAX_REGRAS_POR_TURNO]:
            if isinstance(item, dict):
                texto, escopo = str(item.get("regra") or ""), str(item.get("escopo") or "geral")
            else:
                texto, escopo = str(item), "geral"
            if texto.strip():
                await self._aprendizado.aprender(
                    escritorio_id,
                    texto,
                    escopo=escopo,
                    origem="conversa",
                    criado_por=user_id,
                )

    async def _extrair(self, pedido: str, resposta: str) -> dict[str, Any] | None:
        assert self._ia is not None
        conteudo = (
            f"PEDIDO DO USUÁRIO:\n{pedido[:_MAX_PEDIDO]}\n\n"
            f"RESPOSTA DO ASSISTENTE:\n{resposta[:_MAX_RESPOSTA]}"
        )
        msg = await self._ia.messages.create(
            model=MODELO_EXTRACAO,
            max_tokens=_MAX_TOKENS_EXTRACAO,
            system=_PROMPT_EXTRACAO,
            messages=[{"role": "user", "content": conteudo}],
        )
        bruto = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        achado = re.search(r"\{.*\}", bruto, re.S)
        if not achado:
            return None
        try:
            dados = json.loads(achado.group(0))
        except json.JSONDecodeError:
            return None
        return dados if isinstance(dados, dict) else None

    async def _condominio_por_nome(self, escritorio_id: str, nome: str) -> str | None:
        if nome.strip().lower() in ("", "null", "none", "nenhum"):
            return None
        achado = await self._condominio_citado(escritorio_id, nome)
        return str(achado["id"]) if achado else None

    async def _gravar_fatos(
        self, escritorio_id: str, condominio_id: str, fatos: list[Any]
    ) -> None:
        candidatos = [str(f).strip() for f in fatos if str(f).strip()][:_MAX_FATOS_POR_TURNO]
        if not candidatos:
            return
        existentes = (
            await self._db.table("condominio_fatos")
            .select("fato")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", condominio_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        conhecidos = [f["fato"] for f in (existentes.data or [])]
        novos: list[dict[str, Any]] = []
        for fato in candidatos:
            if len(fato) < 12 or any(fato_repetido(fato, c) for c in conhecidos):
                continue
            conhecidos.append(fato)
            novos.append(
                {
                    "escritorio_id": escritorio_id,
                    "condominio_id": condominio_id,
                    "fato": fato[:500],
                    "origem": "agente",
                }
            )
        if novos:
            await self._db.table("condominio_fatos").insert(novos).execute()

