"""Gestão condominial: coleta diária do EasyJur e do Tiflux e o diário do Hub.

Todo dia o Hub varre o EasyJur (processos) e o Tiflux (tickets) e grava, por
condomínio:

- **eventos** (``eventos_condominio``): processo novo, andamento, processo
  encerrado, ticket aberto, ticket encerrado — cada um com uma ``chave`` que
  torna a coleta idempotente (rodar duas vezes no mesmo dia não duplica);
- a **foto do dia** (``fotos_diarias``): processos ativos, valor em causa,
  tickets abertos.

Por que guardar em vez de consultar as APIs na hora: o EasyJur só guarda o
ÚLTIMO andamento de cada processo — o de ontem some quando chega o de hoje. Só
coletando todo dia a história fica completa. E um relatório de um ano inteiro
sai do nosso banco em milissegundos, sem varrer 49 páginas de API.

A primeira coleta já traz o passado: todo processo tem data de distribuição e
de encerramento, e o Tiflux devolve os tickets de todos os tempos.
"""

import asyncio
import hashlib
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from app.agents.ferramentas_mcpai import (
    ROTA_TICKETS,
    TIFLUX_LIMIT_MAX,
    data_iso,
    em_paralelo,
    limpar_html,
    varrer_processos,
)
from app.services.mcpai import MCPAIClient
from supabase import AsyncClient

# Brasília sem horário de verão desde 2019: um deslocamento fixo dispensa a base
# de fusos (que a imagem slim do Docker e o Windows não trazem).
FUSO = timezone(timedelta(hours=-3), "America/Sao_Paulo")

_ROTA_CLIENTES_TIFLUX = "/api/tiflux/list/clients"
_LOTE_GRAVACAO = 500
# PostgREST devolve no máximo 1.000 linhas por chamada.
_PAGINA_BANCO = 1_000
# Teto de eventos lidos para montar um relatório (um ano do escritório inteiro
# fica bem abaixo disso).
_EVENTOS_MAX = 30_000
# Na coleta incremental, relê os tickets criados nos últimos dias (cobre fim de
# semana sem ninguém abrir o Hub).
_DIAS_RELEITURA_TICKETS = 4
# Uma coleta "rodando" há mais tempo que isto morreu com o servidor.
_COLETA_TRAVADA = timedelta(minutes=20)

_PALAVRAS_VAZIAS = {
    "condominio",
    "condominios",
    "cond",
    "residencial",
    "edificio",
    "ed",
    "do",
    "da",
    "de",
    "dos",
    "das",
    "e",
    "o",
    "a",
}
_ROMANOS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

TIPOS_EVENTO = {
    "processo_novo": "Processo novo",
    "andamento": "Andamento",
    "processo_encerrado": "Processo encerrado",
    "ticket_aberto": "Ticket aberto",
    "ticket_fechado": "Ticket encerrado",
    "nota": "Anotação",
}


class GestaoError(Exception):
    """Erro de negócio na gestão condominial."""

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


def hoje() -> date:
    """Data de hoje no fuso do escritório (Brasília)."""
    return datetime.now(FUSO).date()


# ─── Nomes: casar o "CONDOMINIO SQB" do Tiflux com o do EasyJur ────────────────


def normalizar_nome(nome: str) -> str:
    """Minúsculas, sem acento e sem pontuação — base de toda comparação de nome."""
    sem_acento = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento.lower()))


def _tokens(nome: str) -> set[str]:
    return {t for t in normalizar_nome(nome).split() if t not in _PALAVRAS_VAZIAS}


def _sobra_e_sigla(sobra: set[str]) -> bool:
    """Palavra a mais que ainda é o mesmo condomínio: uma sigla ("sqb").

    Número, quadra ("q04") e romano ("ii") mudam o condomínio — Conquista Ville
    Q03 e Q04 são clientes diferentes.
    """
    return all(t.isalpha() and len(t) <= 4 and t not in _ROMANOS for t in sobra)


def mesmo_condominio(a: str, b: str) -> bool:
    """Diz se dois nomes cadastrados em sistemas diferentes são o mesmo cliente."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    menor, maior = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(menor) >= 2 and menor <= maior and _sobra_e_sigla(maior - menor):
        return True
    razao = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return razao >= 0.93 and not any(re.search(r"\d", t) for t in ta ^ tb)


def contem_nome(maior: str, menor: str) -> bool:
    """Todos os nomes próprios de ``menor`` estão em ``maior`` (sem mudar de unidade)."""
    tm, tM = _tokens(menor), _tokens(maior)
    if not tm or not tm <= tM or not any(len(t) >= 5 for t in tm):
        return False
    return not any(re.search(r"\d", t) or t in _ROMANOS for t in tM - tm)


_MARCAS_CONDOMINIO = (
    "condominio",
    "cond",
    "residencial",
    "residence",
    "edificio",
    "associacao",
    "bloco",
    "bl",
    "sqn",
    "sqs",
    "shcgn",
    "quadra",
    "ville",
    "park",
    "loja",
)


def parece_condominio(nome: str) -> bool:
    """Separa condomínio de perito, cartório, tribunal e fornecedor no Tiflux."""
    return any(t in _MARCAS_CONDOMINIO for t in normalizar_nome(nome).split())


# ─── De registro de API para evento ───────────────────────────────────────────


def _num(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return round(numero, 2) if numero else None


def _nome(valor: Any) -> str:
    if isinstance(valor, dict):
        return str(valor.get("name") or valor.get("nome") or "")
    return str(valor or "")


def andamento(texto: Any) -> tuple[str | None, str]:
    """Separa "dd/mm/aaaa - texto" do último andamento em (data ISO, texto limpo)."""
    limpo = str(limpar_html(texto or "") or "")
    achado = re.match(r"\s*(\d{2}/\d{2}/\d{4})\s*-?\s*(.*)", limpo, re.S)
    if not achado:
        return None, limpo
    return data_iso(achado.group(1)), achado.group(2).strip()


def cliente_do_processo(processo: dict[str, Any]) -> tuple[str | None, str]:
    """(id, nome) do cliente do escritório naquele processo."""
    info = processo.get("cliente_info") or {}
    ident = processo.get("id_cliente") or (info.get("id") if isinstance(info, dict) else None)
    nome = _nome(info) or str(processo.get("nome_cliente") or "")
    return (str(ident) if ident else None), nome


def eventos_de_processo(processo: dict[str, Any]) -> list[dict[str, Any]]:
    """Os eventos que um processo do EasyJur documenta (sem ids do Hub ainda)."""
    pid = processo.get("id_processo")
    if not pid:
        return []
    numero = processo.get("numero") or processo.get("outro_numero") or f"EasyJur {pid}"
    acao = processo.get("titulo_acao") or "Ação"
    contrario = processo.get("nome_contrario")
    local = " · ".join(str(x) for x in (processo.get("vara"), processo.get("uf")) if x)
    dados = {
        "id_processo": pid,
        "status": processo.get("status_label"),
        "fase": processo.get("fase_atual"),
    }
    eventos: list[dict[str, Any]] = []

    distribuido = data_iso(processo.get("data_distribuicao"))
    inicio = distribuido or data_iso(processo.get("data_cadastro"))
    if inicio:
        eventos.append(
            {
                "fonte": "easyjur",
                "tipo": "processo_novo",
                "chave": f"ej:novo:{pid}",
                "referencia": numero,
                "titulo": f"{acao}" + (f" contra {contrario}" if contrario else ""),
                "descricao": local or None,
                "valor": _num(processo.get("valor_causa")),
                "ocorrido_em": inicio,
                # Cobrança extrajudicial não tem distribuição: vale a data de cadastro.
                "dados": {**dados, "base": "distribuicao" if distribuido else "cadastro"},
            }
        )

    fim = data_iso(processo.get("data_encerramento"))
    if fim:
        eventos.append(
            {
                "fonte": "easyjur",
                "tipo": "processo_encerrado",
                "chave": f"ej:enc:{pid}",
                "referencia": numero,
                "titulo": f"Encerrado: {acao}" + (f" contra {contrario}" if contrario else ""),
                "descricao": processo.get("resultado_label") or None,
                "valor": _num(processo.get("valor_causa")),
                "ocorrido_em": fim,
                "dados": dados,
            }
        )

    quando, texto = andamento(processo.get("ultimo_andamento"))
    if quando and texto:
        impressao = hashlib.sha1(texto.encode()).hexdigest()[:10]
        eventos.append(
            {
                "fonte": "easyjur",
                "tipo": "andamento",
                "chave": f"ej:and:{pid}:{quando}:{impressao}",
                "referencia": numero,
                "titulo": texto[:160],
                "descricao": texto[:800] if len(texto) > 160 else None,
                "valor": None,
                "ocorrido_em": quando,
                "dados": dados,
            }
        )
    return eventos


def eventos_de_ticket(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Abertura (e encerramento, se já encerrado) de um ticket do Tiflux."""
    numero = ticket.get("ticket_number")
    criado = data_iso(ticket.get("created_at"))
    if not numero or not criado:
        return []
    detalhe = " · ".join(
        f"{rotulo} {_nome(ticket.get(campo))}"
        for rotulo, campo in (("mesa", "desk"), ("resp.", "responsible"))
        if _nome(ticket.get(campo))
    )
    dados = {
        "estagio": _nome(ticket.get("stage")),
        "responsavel": _nome(ticket.get("responsible")),
        "mesa": _nome(ticket.get("desk")),
    }
    titulo = str(ticket.get("title") or "Sem título")[:160]
    eventos = [
        {
            "fonte": "tiflux",
            "tipo": "ticket_aberto",
            "chave": f"tf:ab:{numero}",
            "referencia": f"#{numero}",
            "titulo": titulo,
            "descricao": detalhe or None,
            "valor": None,
            "ocorrido_em": criado,
            "dados": dados,
        }
    ]
    if ticket.get("is_closed"):
        # O Tiflux não informa a data de encerramento; a última atualização de um
        # ticket fechado é o melhor retrato dela.
        fechado = data_iso(ticket.get("updated_at")) or criado
        eventos.append({**eventos[0], "tipo": "ticket_fechado", "chave": f"tf:fe:{numero}",
                        "ocorrido_em": fechado})
    return eventos


def _ativo(processo: dict[str, Any]) -> bool:
    return str(processo.get("status_label") or "").lower() == "ativo"


# ─── Serviço ──────────────────────────────────────────────────────────────────

_EM_ANDAMENTO: set[asyncio.Task[Any]] = set()


class GestaoService:
    """Coleta diária e consultas ao diário dos condomínios de um escritório."""

    def __init__(self, supabase: AsyncClient, mcp: MCPAIClient | None = None) -> None:
        self._db = supabase
        self._mcp = mcp

    # ── Coleta ─────────────────────────────────────────────────────────────

    def disparar_coleta(self, escritorio_id: str) -> None:
        """Roda a coleta em segundo plano (quem pediu não espera)."""
        tarefa = asyncio.create_task(self._coleta_silenciosa(escritorio_id))
        _EM_ANDAMENTO.add(tarefa)
        tarefa.add_done_callback(_EM_ANDAMENTO.discard)

    async def _coleta_silenciosa(self, escritorio_id: str) -> None:
        try:
            await self.sincronizar(escritorio_id)
        except Exception:  # noqa: BLE001 - o erro fica registrado em `sincronizacoes`
            pass

    async def garantir_coleta_do_dia(self, escritorio_id: str) -> bool:
        """Dispara a coleta se ainda não houve uma hoje. Devolve se disparou."""
        if self._mcp is None or not self._mcp.ativo:
            return False
        ultima = await self.ultima_coleta(escritorio_id)
        if ultima:
            if ultima.get("status") == "ok" and ultima.get("dia") == hoje().isoformat():
                return False
            if ultima.get("status") == "rodando" and not self.travada(ultima):
                return False
        self.disparar_coleta(escritorio_id)
        return True

    @staticmethod
    def travada(coleta: dict[str, Any]) -> bool:
        try:
            inicio = datetime.fromisoformat(str(coleta.get("iniciada_em")))
        except ValueError:
            return True
        return datetime.now(inicio.tzinfo or FUSO) - inicio > _COLETA_TRAVADA

    async def ultima_coleta(self, escritorio_id: str) -> dict[str, Any] | None:
        result = (
            await self._db.table("sincronizacoes")
            .select("id,dia,status,iniciada_em,concluida_em,resumo,erro")
            .eq("escritorio_id", escritorio_id)
            .order("iniciada_em", desc=True)
            .limit(1)
            .execute()
        )
        linhas = result.data or []
        return linhas[0] if linhas else None

    async def _ultima_ok(self, escritorio_id: str) -> dict[str, Any] | None:
        result = (
            await self._db.table("sincronizacoes")
            .select("id,dia,resumo")
            .eq("escritorio_id", escritorio_id)
            .eq("status", "ok")
            .order("iniciada_em", desc=True)
            .limit(1)
            .execute()
        )
        linhas = result.data or []
        return linhas[0] if linhas else None

    async def sincronizar(self, escritorio_id: str, *, completa: bool = False) -> dict[str, Any]:
        """Coleta EasyJur + Tiflux, grava os eventos novos e a foto do dia.

        Args:
            escritorio_id: Escritório dono dos dados.
            completa: Relê todos os tickets do Tiflux (a primeira coleta já é
                completa sozinha).

        Returns:
            Resumo da coleta (processos, tickets, eventos novos, condomínios).
        """
        if self._mcp is None or not self._mcp.ativo:
            raise GestaoError("EasyJur/Tiflux não configurados neste servidor.", status=503)
        dia = hoje()
        registro = (
            await self._db.table("sincronizacoes")
            .insert({"escritorio_id": escritorio_id, "dia": dia.isoformat()})
            .execute()
        )
        coleta_id = (registro.data or [{}])[0].get("id")
        try:
            resumo = await self._coletar(escritorio_id, dia, completa=completa)
        except Exception as exc:
            if coleta_id:
                await self._db.table("sincronizacoes").update(
                    {"status": "erro", "erro": str(exc)[:1000],
                     "concluida_em": datetime.now(FUSO).isoformat()}
                ).eq("id", coleta_id).execute()
            raise
        if coleta_id:
            await self._db.table("sincronizacoes").update(
                {"status": "ok", "resumo": resumo, "concluida_em": datetime.now(FUSO).isoformat()}
            ).eq("id", coleta_id).execute()
        return resumo

    async def _coletar(self, escritorio_id: str, dia: date, *, completa: bool) -> dict[str, Any]:
        assert self._mcp is not None
        anterior = await self._ultima_ok(escritorio_id)
        abertos_antes: dict[str, Any] = dict((anterior or {}).get("resumo", {}).get(
            "tickets_abertos_ids", {}
        ))
        completa = completa or anterior is None

        processos, total_ej, _, falhas_ej = await varrer_processos(self._mcp, {})
        clientes_tf = await self._clientes_tiflux()
        tickets, abertos, falhas_tf = await self._tickets(dia, completa=completa)

        mapa_ej, mapa_tf = await self._vincular(escritorio_id, processos, clientes_tf)

        linhas: list[dict[str, Any]] = []
        for processo in processos:
            cliente_id, _ = cliente_do_processo(processo)
            condominio = mapa_ej.get(cliente_id) if cliente_id else None
            for evento in eventos_de_processo(processo):
                linhas.append({**evento, "escritorio_id": escritorio_id,
                               "condominio_id": condominio})
        for ticket in tickets:
            condominio = mapa_tf.get(str((ticket.get("client") or {}).get("id")))
            for evento in eventos_de_ticket(ticket):
                linhas.append({**evento, "escritorio_id": escritorio_id,
                               "condominio_id": condominio})

        # Ticket que estava aberto na coleta anterior e sumiu da lista de abertos
        # foi encerrado entre uma coleta e outra.
        abertos_agora = {str(t.get("ticket_number")): t for t in abertos}
        for numero, info in abertos_antes.items():
            if numero in abertos_agora:
                continue
            linhas.append(
                {
                    "escritorio_id": escritorio_id,
                    "condominio_id": mapa_tf.get(str(info.get("cliente"))),
                    "fonte": "tiflux",
                    "tipo": "ticket_fechado",
                    "chave": f"tf:fe:{numero}",
                    "referencia": f"#{numero}",
                    "titulo": str(info.get("titulo") or "Ticket")[:160],
                    "descricao": None,
                    "valor": None,
                    "ocorrido_em": dia.isoformat(),
                    "dados": {},
                }
            )

        novos = await self._gravar_eventos(linhas)
        condominios_com_foto = await self._gravar_fotos(
            escritorio_id, dia, processos, abertos, mapa_ej, mapa_tf
        )
        return {
            "processos": len(processos),
            "processos_total_api": total_ej,
            "tickets_lidos": len(tickets),
            "tickets_abertos": len(abertos),
            "eventos_novos": novos,
            "condominios": condominios_com_foto,
            "completa": completa,
            "falhas": falhas_ej + falhas_tf,
            "tickets_abertos_ids": {
                numero: {
                    "cliente": (t.get("client") or {}).get("id"),
                    "titulo": str(t.get("title") or "")[:160],
                }
                for numero, t in abertos_agora.items()
            },
        }

    async def _clientes_tiflux(self) -> list[dict[str, Any]]:
        assert self._mcp is not None
        clientes: list[dict[str, Any]] = []
        for pagina in range(1, 11):
            resposta = await self._mcp.chamar(
                _ROTA_CLIENTES_TIFLUX, {"limit": TIFLUX_LIMIT_MAX, "offset": pagina}
            )
            lote = resposta.get("value") or []
            clientes.extend(lote)
            if len(lote) < TIFLUX_LIMIT_MAX:
                break
        return clientes

    async def _paginas_tickets(self, filtros: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """Todas as páginas de uma consulta de tickets (offset = nº da página)."""
        assert self._mcp is not None
        mcp = self._mcp
        base = {**filtros, "limit": TIFLUX_LIMIT_MAX}
        primeira = await mcp.chamar(ROTA_TICKETS, {**base, "offset": 1})
        itens = list(primeira.get("value") or [])
        total = int(primeira.get("total_items") or len(itens))
        paginas = max(1, -(-total // TIFLUX_LIMIT_MAX))

        def pagina(numero: int) -> Callable[[], Awaitable[list[dict[str, Any]]]]:
            async def buscar() -> list[dict[str, Any]]:
                resposta = await mcp.chamar(ROTA_TICKETS, {**base, "offset": numero})
                return resposta.get("value") or []

            return buscar

        lotes, falhas = await em_paralelo([pagina(n) for n in range(2, paginas + 1)])
        for lote in lotes:
            itens.extend(lote)
        return itens, falhas

    async def _tickets(
        self, dia: date, *, completa: bool
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """(tickets para gerar eventos, tickets abertos agora, páginas que falharam)."""
        abertos, falhas = await self._paginas_tickets({"filter_by": "open"})
        if completa:
            todos, falhas_todos = await self._paginas_tickets({"filter_by": "all"})
        else:
            desde = dia - timedelta(days=_DIAS_RELEITURA_TICKETS)
            todos, falhas_todos = await self._paginas_tickets(
                {"filter_by": "all", "start_datetime": f"{desde.isoformat()}T00:00:00"}
            )
        vistos = {t.get("ticket_number"): t for t in [*todos, *abertos]}
        return list(vistos.values()), abertos, falhas + falhas_todos

    async def _condominios(self, escritorio_id: str) -> list[dict[str, Any]]:
        result = (
            await self._db.table("condominios")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        return list(result.data or [])

    async def _vincular(
        self,
        escritorio_id: str,
        processos: list[dict[str, Any]],
        clientes_tf: list[dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Garante um condomínio no Hub para cada cliente do EasyJur e do Tiflux.

        Returns:
            (id do cliente EasyJur → id do condomínio, id do cliente Tiflux → id).
        """
        existentes = await self._condominios(escritorio_id)
        por_nome = {normalizar_nome(c["nome"]): c for c in existentes}
        mapa_ej = {
            str(c["easyjur_cliente_id"]): str(c["id"])
            for c in existentes
            if c.get("easyjur_cliente_id")
        }
        mapa_tf = {
            str(c["tiflux_cliente_id"]): str(c["id"])
            for c in existentes
            if c.get("tiflux_cliente_id")
        }

        clientes_ej: dict[str, str] = {}
        for processo in processos:
            ident, nome = cliente_do_processo(processo)
            if ident and nome:
                clientes_ej.setdefault(ident, nome)

        vinculos: list[dict[str, Any]] = []
        novos: dict[str, dict[str, Any]] = {}

        def achar(nome: str, campo: str) -> dict[str, Any] | None:
            chave = normalizar_nome(nome)
            if chave in por_nome:
                return por_nome[chave]
            livres = [c for c in [*existentes, *novos.values()] if not c.get(campo)]
            for condominio in livres:
                if mesmo_condominio(condominio["nome"], nome):
                    return condominio
            # "CONDOMINIO RESIDENCIAL CASABLANCA" (Tiflux) é o "CONDOMINIO CASABLANCA
            # MALL RESIDENCE" (EasyJur) quando só um condomínio tem aquele nome próprio.
            contidos = [c for c in livres if contem_nome(c["nome"], nome)]
            return contidos[0] if len(contidos) == 1 else None

        for ident, nome in clientes_ej.items():
            if ident in mapa_ej:
                continue
            alvo = achar(nome, "easyjur_cliente_id")
            if alvo is None:
                novo = {"escritorio_id": escritorio_id, "nome": nome.strip(),
                        "easyjur_cliente_id": ident, "origem": "easyjur"}
                novos[normalizar_nome(nome)] = novo
                por_nome[normalizar_nome(nome)] = novo
            elif not alvo.get("easyjur_cliente_id"):
                alvo["easyjur_cliente_id"] = ident
                if alvo.get("id"):
                    vinculos.append(alvo)
            else:
                # Cliente duplicado no EasyJur (mesmo nome, outro id): as duas
                # fichas apontam para o mesmo condomínio do Hub.
                mapa_ej[ident] = str(alvo.get("id") or "")

        for cliente in clientes_tf:
            ident, nome = str(cliente.get("id") or ""), str(cliente.get("name") or "")
            if not ident or not nome or ident in mapa_tf or "teste" in nome.lower():
                continue
            alvo = achar(nome, "tiflux_cliente_id")
            if alvo is None:
                if not parece_condominio(nome):
                    # Perito, cartório, tribunal, fornecedor: os tickets entram no
                    # diário "sem vínculo", mas não viram condomínio na lista.
                    continue
                novo = {"escritorio_id": escritorio_id, "nome": nome.strip(),
                        "tiflux_cliente_id": ident, "origem": "tiflux"}
                novos[normalizar_nome(nome)] = novo
                por_nome[normalizar_nome(nome)] = novo
            elif not alvo.get("tiflux_cliente_id"):
                alvo["tiflux_cliente_id"] = ident
                if alvo.get("id"):
                    vinculos.append(alvo)

        if novos:
            criados = await self._db.table("condominios").insert(list(novos.values())).execute()
            for linha in criados.data or []:
                if linha.get("easyjur_cliente_id"):
                    mapa_ej[str(linha["easyjur_cliente_id"])] = str(linha["id"])
                if linha.get("tiflux_cliente_id"):
                    mapa_tf[str(linha["tiflux_cliente_id"])] = str(linha["id"])
        if vinculos:
            await self._db.table("condominios").upsert(
                [
                    {
                        "id": c["id"],
                        "escritorio_id": escritorio_id,
                        "nome": c["nome"],
                        "easyjur_cliente_id": c.get("easyjur_cliente_id"),
                        "tiflux_cliente_id": c.get("tiflux_cliente_id"),
                    }
                    for c in vinculos
                ],
                on_conflict="id",
            ).execute()
            for c in vinculos:
                if c.get("easyjur_cliente_id"):
                    mapa_ej[str(c["easyjur_cliente_id"])] = str(c["id"])
                if c.get("tiflux_cliente_id"):
                    mapa_tf[str(c["tiflux_cliente_id"])] = str(c["id"])

        # Duplicados do EasyJur cujo "alvo" acabou de ser criado nesta coleta.
        for ident, nome in clientes_ej.items():
            if not mapa_ej.get(ident):
                alvo = por_nome.get(normalizar_nome(nome)) or {}
                destino = mapa_ej.get(str(alvo.get("easyjur_cliente_id")))
                if destino:
                    mapa_ej[ident] = destino
        return {k: v for k, v in mapa_ej.items() if v}, mapa_tf

    async def _gravar_eventos(self, linhas: list[dict[str, Any]]) -> int:
        """Grava só o que é novo (a chave única descarta o que já estava lá)."""
        unicas = list({(ln["escritorio_id"], ln["chave"]): ln for ln in linhas}.values())
        novos = 0
        for inicio in range(0, len(unicas), _LOTE_GRAVACAO):
            lote = unicas[inicio : inicio + _LOTE_GRAVACAO]
            result = (
                await self._db.table("eventos_condominio")
                .upsert(lote, on_conflict="escritorio_id,chave", ignore_duplicates=True)
                .execute()
            )
            novos += len(result.data or [])
        return novos

    async def _gravar_fotos(
        self,
        escritorio_id: str,
        dia: date,
        processos: list[dict[str, Any]],
        abertos: list[dict[str, Any]],
        mapa_ej: dict[str, str],
        mapa_tf: dict[str, str],
    ) -> int:
        fotos: dict[str, dict[str, Any]] = {}

        def foto(condominio_id: str) -> dict[str, Any]:
            return fotos.setdefault(
                condominio_id,
                {
                    "condominio_id": condominio_id,
                    "escritorio_id": escritorio_id,
                    "dia": dia.isoformat(),
                    "processos_ativos": 0,
                    "processos_total": 0,
                    "valor_causas_ativas": 0.0,
                    "tickets_abertos": 0,
                    "dados": {},
                },
            )

        for processo in processos:
            cliente_id, _ = cliente_do_processo(processo)
            condominio = mapa_ej.get(cliente_id) if cliente_id else None
            if not condominio:
                continue
            f = foto(condominio)
            f["processos_total"] += 1
            if _ativo(processo):
                f["processos_ativos"] += 1
                f["valor_causas_ativas"] += _num(processo.get("valor_causa")) or 0.0
        for ticket in abertos:
            condominio = mapa_tf.get(str((ticket.get("client") or {}).get("id")))
            if condominio:
                foto(condominio)["tickets_abertos"] += 1
        for f in fotos.values():
            f["valor_causas_ativas"] = round(f["valor_causas_ativas"], 2)

        lista = list(fotos.values())
        for inicio in range(0, len(lista), _LOTE_GRAVACAO):
            await self._db.table("fotos_diarias").upsert(
                lista[inicio : inicio + _LOTE_GRAVACAO], on_conflict="condominio_id,dia"
            ).execute()
        return len(lista)

    # ── Consultas ──────────────────────────────────────────────────────────

    async def listar_condominios(
        self, escritorio_id: str, busca: str = ""
    ) -> list[dict[str, Any]]:
        """Condomínios do escritório com a foto mais recente de cada um."""
        condominios = await self._condominios(escritorio_id)
        if busca.strip():
            alvo = normalizar_nome(busca)
            condominios = [
                c for c in condominios
                if alvo in normalizar_nome(c["nome"]) or mesmo_condominio(c["nome"], busca)
            ]
        fotos = await self._fotos_recentes(escritorio_id)
        saida = []
        for c in condominios:
            f = fotos.get(str(c["id"]), {})
            saida.append(
                {
                    **{k: c.get(k) for k in (
                        "id", "nome", "cnpj", "endereco", "cidade", "uf", "sindico",
                        "administradora", "status", "observacoes", "easyjur_cliente_id",
                        "tiflux_cliente_id", "origem",
                    )},
                    "processos_ativos": f.get("processos_ativos", 0),
                    "processos_total": f.get("processos_total", 0),
                    "valor_causas_ativas": float(f.get("valor_causas_ativas") or 0),
                    "tickets_abertos": f.get("tickets_abertos", 0),
                    "foto_de": f.get("dia"),
                }
            )
        saida.sort(key=lambda c: (-c["processos_ativos"], -c["tickets_abertos"], c["nome"]))
        return saida

    async def _fotos_recentes(self, escritorio_id: str) -> dict[str, dict[str, Any]]:
        ultimo = (
            await self._db.table("fotos_diarias")
            .select("dia")
            .eq("escritorio_id", escritorio_id)
            .order("dia", desc=True)
            .limit(1)
            .execute()
        )
        if not ultimo.data:
            return {}
        dia = ultimo.data[0]["dia"]
        linhas = await self._paginar(
            lambda: self._db.table("fotos_diarias")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .eq("dia", dia)
        )
        return {str(f["condominio_id"]): f for f in linhas}

    async def _paginar(self, consulta: Callable[[], Any], teto: int = _EVENTOS_MAX) -> list[Any]:
        """Lê além das 1.000 linhas por chamada do PostgREST."""
        linhas: list[Any] = []
        while len(linhas) < teto:
            inicio = len(linhas)
            lote = (await consulta().range(inicio, inicio + _PAGINA_BANCO - 1).execute()).data
            linhas.extend(lote or [])
            if not lote or len(lote) < _PAGINA_BANCO:
                break
        return linhas

    async def buscar_condominio(self, escritorio_id: str, nome: str) -> dict[str, Any]:
        """Acha UM condomínio pelo nome como o usuário fala ("o SQB", "Casablanca").

        Raises:
            GestaoError: 404 se nenhum bater; 409 com os candidatos se vários baterem.
        """
        condominios = await self._condominios(escritorio_id)
        alvo = normalizar_nome(nome)
        exatos = [c for c in condominios if normalizar_nome(c["nome"]) == alvo]
        if exatos:
            return exatos[0]
        tokens = _tokens(nome)
        candidatos = [
            c for c in condominios
            if mesmo_condominio(c["nome"], nome)
            or (tokens and tokens <= _tokens(c["nome"]))
            or (alvo and alvo in normalizar_nome(c["nome"]))
        ]
        if len(candidatos) == 1:
            return candidatos[0]
        if not candidatos:
            raise GestaoError(f"Nenhum condomínio do Hub bate com '{nome}'.", status=404)
        nomes = "; ".join(c["nome"] for c in candidatos[:12])
        raise GestaoError(f"Mais de um condomínio bate com '{nome}': {nomes}.", status=409)

    async def obter(self, escritorio_id: str, condominio_id: str) -> dict[str, Any]:
        result = (
            await self._db.table("condominios")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .eq("id", condominio_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise GestaoError("Condomínio não encontrado.", status=404)
        return result.data[0]

    async def detalhe(self, escritorio_id: str, condominio_id: str) -> dict[str, Any]:
        """Cadastro, memória, evolução (fotos) e eventos recentes de um condomínio."""
        condominio = await self.obter(escritorio_id, condominio_id)
        fatos = (
            await self._db.table("condominio_fatos")
            .select("fato,origem,created_at")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", condominio_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        fotos = (
            await self._db.table("fotos_diarias")
            .select("dia,processos_ativos,processos_total,valor_causas_ativas,tickets_abertos")
            .eq("condominio_id", condominio_id)
            .order("dia", desc=True)
            .limit(120)
            .execute()
        )
        eventos = (
            await self._db.table("eventos_condominio")
            .select("fonte,tipo,referencia,titulo,descricao,valor,ocorrido_em")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", condominio_id)
            .order("ocorrido_em", desc=True)
            .limit(60)
            .execute()
        )
        return {
            "condominio": condominio,
            "memoria": fatos.data or [],
            "evolucao": list(reversed(fotos.data or [])),
            "eventos_recentes": eventos.data or [],
        }

    async def eventos(
        self,
        escritorio_id: str,
        *,
        inicio: date,
        fim: date,
        condominio_id: str | None = None,
        fonte: str | None = None,
        tipo: str | None = None,
    ) -> dict[str, Any]:
        """O diário de um período, com o resumo pronto para relatório."""

        def consulta() -> Any:
            q = (
                self._db.table("eventos_condominio")
                .select("condominio_id,fonte,tipo,referencia,titulo,descricao,valor,ocorrido_em")
                .eq("escritorio_id", escritorio_id)
                .gte("ocorrido_em", inicio.isoformat())
                .lte("ocorrido_em", fim.isoformat())
            )
            if condominio_id:
                q = q.eq("condominio_id", condominio_id)
            if fonte:
                q = q.eq("fonte", fonte)
            if tipo:
                q = q.eq("tipo", tipo)
            return q.order("ocorrido_em", desc=True).order("chave")

        linhas = await self._paginar(consulta)
        nomes = {str(c["id"]): c["nome"] for c in await self._condominios(escritorio_id)}
        for linha in linhas:
            linha["condominio"] = nomes.get(str(linha.get("condominio_id")), "Sem vínculo")
        por_tipo = Counter(TIPOS_EVENTO.get(ev["tipo"], ev["tipo"]) for ev in linhas)
        por_condominio = Counter(ev["condominio"] for ev in linhas)
        por_dia = Counter(ev["ocorrido_em"] for ev in linhas)
        valor_novos = sum(
            float(ev.get("valor") or 0) for ev in linhas if ev["tipo"] == "processo_novo"
        )
        return {
            "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
            "total": len(linhas),
            "cortado": len(linhas) >= _EVENTOS_MAX,
            "resumo": {
                "por_tipo": dict(por_tipo.most_common()),
                "por_condominio": dict(por_condominio.most_common(25)),
                "dias_com_movimento": len(por_dia),
                "valor_processos_novos": round(valor_novos, 2),
            },
            "eventos": linhas,
        }

    async def painel(self, escritorio_id: str, dia: date | None = None) -> dict[str, Any]:
        """O que aconteceu num dia, mais os totais do escritório."""
        dia = dia or hoje()
        diario = await self.eventos(escritorio_id, inicio=dia, fim=dia)
        condominios = await self.listar_condominios(escritorio_id)
        com_dados = [c for c in condominios if c["processos_total"] or c["tickets_abertos"]]
        return {
            "dia": dia.isoformat(),
            "ultima_coleta": await self.ultima_coleta(escritorio_id),
            "totais": {
                "condominios": len(com_dados) or len(condominios),
                "processos_ativos": sum(c["processos_ativos"] for c in condominios),
                "valor_causas_ativas": round(
                    sum(c["valor_causas_ativas"] for c in condominios), 2
                ),
                "tickets_abertos": sum(c["tickets_abertos"] for c in condominios),
                "eventos_do_dia": diario["total"],
            },
            "resumo_do_dia": diario["resumo"],
            "eventos_do_dia": diario["eventos"][:300],
            "destaques": condominios[:12],
        }

    # ── Escrita ────────────────────────────────────────────────────────────

    _CAMPOS_EDITAVEIS = (
        "nome", "cnpj", "endereco", "cidade", "uf", "sindico", "administradora",
        "status", "observacoes", "easyjur_cliente_id", "tiflux_cliente_id",
    )

    async def atualizar(
        self, escritorio_id: str, condominio_id: str, campos: dict[str, Any]
    ) -> dict[str, Any]:
        """Atualiza o cadastro (só os campos editáveis, sempre dentro do escritório)."""
        await self.obter(escritorio_id, condominio_id)
        dados = {
            k: (str(v).strip() or None) if v is not None else None
            for k, v in campos.items()
            if k in self._CAMPOS_EDITAVEIS
        }
        if not dados:
            raise GestaoError("Nada para atualizar.")
        if "nome" in dados and not dados["nome"]:
            raise GestaoError("O nome não pode ficar vazio.")
        dados["atualizado_em"] = datetime.now(FUSO).isoformat()
        result = (
            await self._db.table("condominios")
            .update(dados)
            .eq("escritorio_id", escritorio_id)
            .eq("id", condominio_id)
            .execute()
        )
        return (result.data or [{}])[0]

    async def registrar_evento(
        self,
        escritorio_id: str,
        condominio_id: str,
        *,
        titulo: str,
        descricao: str = "",
        dia: date | None = None,
    ) -> dict[str, Any]:
        """Anotação do escritório no diário (reunião, assembleia, ligação...)."""
        await self.obter(escritorio_id, condominio_id)
        linha = {
            "escritorio_id": escritorio_id,
            "condominio_id": condominio_id,
            "fonte": "hub",
            "tipo": "nota",
            "chave": f"hub:{uuid.uuid4()}",
            "titulo": titulo.strip()[:300],
            "descricao": descricao.strip() or None,
            "ocorrido_em": (dia or hoje()).isoformat(),
        }
        result = await self._db.table("eventos_condominio").insert(linha).execute()
        return (result.data or [linha])[0]
