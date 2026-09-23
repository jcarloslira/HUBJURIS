"""Dossiê da tratativa — tudo que já houve com aquele condomínio, numa chamada só.

Antes de escrever uma notificação, o advogado abre a pasta do condomínio: vê a
última notificação enviada, em que pé ficou a conversa com o síndico, se já há
processo daquela unidade. O agente precisa fazer o mesmo — e fazia mal, porque
isso exigia dele quatro ou cinco chamadas (ficha, diário, memória, Drive) que ele
economizava justamente quando mais importavam.

Aqui é uma ferramenta só. Ela cruza, em paralelo:

- **Hub** — cadastro do condomínio, fatos aprendidos, movimentos do EasyJur e do
  Tiflux e onde cada demanda anterior parou;
- **Drive** — os documentos mais recentes daquele condomínio (e da unidade, se
  houver), que é onde moram as peças efetivamente enviadas.

Filtrar por unidade é o que torna isto útil de verdade: "Bloco C, apto 42" traz a
notificação daquele apartamento, não as 300 do condomínio.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.composio_drive import ComposioClient
from app.services.gestao import GestaoError, GestaoService
from app.services.memoria import MemoriaService

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# Quanto de cada fonte entra na resposta: o suficiente para decidir, não um despejo.
_EVENTOS = 14
_FATOS = 12
_DEMANDAS = 8
_ARQUIVOS = 8
_LIMITE = 14_000

FERRAMENTAS_DOSSIE: list[dict[str, Any]] = [
    {
        "name": "dossie_da_demanda",
        "description": (
            "O histórico completo de um condomínio (e de uma unidade específica, se "
            "informada) numa única consulta: cadastro, o que o escritório já sabe, os "
            "últimos movimentos do EasyJur e do Tiflux, onde pararam as demandas "
            "anteriores e os documentos mais recentes no Drive. "
            "CHAME ANTES de redigir qualquer peça, responder sobre a situação de um "
            "condomínio ou retomar uma tratativa — é o que te permite dizer 'a última "
            "notificação desta unidade foi em 12/08' em vez de começar do zero. "
            "Uma chamada só substitui hub_condominio + busca no Drive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "condominio": {
                    "type": "string",
                    "description": "Nome do condomínio como o usuário fala ('o SQB', 'Ventura').",
                },
                "unidade": {
                    "type": "string",
                    "description": (
                        "Unidade/apartamento/bloco, quando a demanda for de uma unidade "
                        "(ex.: '204-B', 'Bloco C apto 42'). Filtra o acervo do Drive."
                    ),
                },
                "assunto": {
                    "type": "string",
                    "description": "Tema da tratativa, para focar a busca no Drive.",
                },
            },
            "required": ["condominio"],
        },
    }
]

NOMES_DOSSIE = {f["name"] for f in FERRAMENTAS_DOSSIE}

INSTRUCAO_DOSSIE = """DOSSIÊ ANTES DE AGIR — como um advogado que abre a pasta antes \
de escrever:
- Demanda sobre um condomínio ou unidade específica (redigir peça, notificação, \
cobrança, responder "como está o X", retomar tratativa)? Chame `dossie_da_demanda` \
UMA vez, ANTES de responder, com o condomínio e, se houver, a unidade. Não pergunte \
se pode: ler é interno e instantâneo.
- Use o que voltar para ancorar a resposta em fato, com data: a última peça enviada \
àquela unidade, o último movimento do processo, o ticket ainda aberto, onde a \
conversa anterior parou. Cite isso ao usuário — é o que mostra que você acompanha.
- Achou documento no Drive que serve de padrão? Leia com `ler_documento_drive` e \
siga a forma dele.
- Dúvida jurídica geral, tese, lei, conversa: NÃO chame o dossiê — responda direto."""


def _texto(valor: Any) -> str:
    return " ".join(str(valor or "").split())


def _dia(valor: Any) -> str:
    bruto = str(valor or "")[:10]
    return "/".join(reversed(bruto.split("-"))) if bruto.count("-") == 2 else bruto


def _termos_unidade(unidade: str) -> list[str]:
    """Jeitos de a unidade aparecer no nome do arquivo ('204-B', '204', 'apto 204')."""
    limpo = _texto(unidade)
    if not limpo:
        return []
    numeros = re.findall(r"\d+[-/]?[A-Za-z]?", limpo)
    return list(dict.fromkeys([limpo, *numeros]))[:3]


def montar_handlers_dossie(
    gestao: GestaoService,
    memoria: MemoriaService,
    escritorio_id: str,
    composio: ComposioClient | None = None,
) -> dict[str, Handler]:
    """Handler do dossiê, escopado ao escritório do usuário logado."""

    async def _drive(condominio: str, unidade: str, assunto: str) -> list[str]:
        """Documentos recentes do condomínio no Drive — os mais novos primeiro."""
        if composio is None:
            return []
        alvos = [condominio, *_termos_unidade(unidade)]
        if assunto:
            alvos.append(assunto)
        clausulas = " or ".join(
            f"name contains '{a.replace(chr(39), chr(92) + chr(39))}'" for a in alvos if a
        )
        try:
            data = await composio.executar_acao(
                "GOOGLEDRIVE_LIST_FILES",
                escritorio_id,
                {
                    "q": f"({clausulas}) and trashed = false",
                    "pageSize": _ARQUIVOS * 3,
                    "orderBy": "modifiedTime desc",
                    "fields": "files(id,name,mimeType,modifiedTime)",
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                },
            )
        except Exception:  # noqa: BLE001 - Drive é bônus: o dossiê do Hub já vale
            return []
        arquivos = data.get("files", []) if isinstance(data, dict) else []
        # Com unidade informada, o que cita a unidade vem primeiro: é o que interessa.
        unidades = [u.lower() for u in _termos_unidade(unidade)]
        if unidades:
            arquivos.sort(
                key=lambda a: not any(u in str(a.get("name", "")).lower() for u in unidades)
            )
        return [
            f"- {a.get('name', '?')} · modificado em {_dia(a.get('modifiedTime'))} "
            f"[id: {a.get('id')}]"
            for a in arquivos[:_ARQUIVOS]
        ]

    async def dossie(entrada: dict[str, Any]) -> str:
        nome = _texto(entrada.get("condominio"))
        unidade = _texto(entrada.get("unidade"))
        assunto = _texto(entrada.get("assunto"))
        if not nome:
            return "Informe o condomínio."
        try:
            condominio = await gestao.buscar_condominio(escritorio_id, nome)
        except GestaoError as exc:
            # Sem condomínio no Hub o Drive ainda pode ter o acervo: não devolva vazio.
            arquivos = await _drive(nome, unidade, assunto)
            corpo = "\n".join(arquivos) if arquivos else "(nada no Drive também)"
            return (
                f"{exc}\nNo acervo do Drive encontrei:\n{corpo}\n"
                "Siga com a tarefa usando o que houver e, se fizer sentido, ofereça "
                "cadastrar o condomínio no Hub."
            )

        cid = str(condominio["id"])
        detalhe, demandas, arquivos = await asyncio.gather(
            gestao.detalhe(escritorio_id, cid),
            memoria.historico(escritorio_id, cid),
            _drive(condominio["nome"], unidade, assunto),
        )

        alvo = f"{condominio['nome']}" + (f" · unidade {unidade}" if unidade else "")
        linhas = [f"DOSSIÊ — {alvo}"]

        cadastro = [
            f"{k}: {v}"
            for k, v in (detalhe.get("condominio") or {}).items()
            if v and k in ("cnpj", "sindico", "administradora", "cidade", "uf", "observacoes")
        ]
        if cadastro:
            linhas.append("Cadastro — " + " · ".join(cadastro))

        fatos = detalhe.get("memoria") or []
        if fatos:
            linhas.append("O que o escritório já sabe deste condomínio:")
            linhas += [f"- {f['fato']}" for f in fatos[:_FATOS]]

        if demandas:
            linhas.append("Onde pararam as demandas anteriores:")
            for item in demandas[:_DEMANDAS]:
                pedaco = f"- {_dia(item.get('created_at'))} · {item.get('assunto') or 'demanda'}"
                if item.get("onde_parou"):
                    pedaco += f" — parou em: {item['onde_parou']}"
                if item.get("proximo_passo"):
                    pedaco += f" (próximo: {item['proximo_passo']})"
                linhas.append(pedaco)

        eventos = detalhe.get("eventos_recentes") or []
        if unidade:
            # A unidade costuma aparecer no título do processo/ticket.
            marcas = [u.lower() for u in _termos_unidade(unidade)]
            daquela = [
                e
                for e in eventos
                if any(m in f"{e.get('titulo')} {e.get('descricao')}".lower() for m in marcas)
            ]
            eventos = daquela + [e for e in eventos if e not in daquela]
        if eventos:
            linhas.append("Últimos movimentos (EasyJur/Tiflux/Hub):")
            for evento in eventos[:_EVENTOS]:
                valor = f" · R$ {evento['valor']}" if evento.get("valor") else ""
                linhas.append(
                    f"- {_dia(evento.get('ocorrido_em'))} · {evento.get('fonte')} · "
                    f"{evento.get('tipo')} · {evento.get('referencia') or ''} "
                    f"{_texto(evento.get('titulo'))[:150]}{valor}".strip()
                )

        if arquivos:
            linhas.append("Documentos mais recentes no Drive (leia o que servir de padrão):")
            linhas += arquivos
        elif composio is not None:
            linhas.append(
                "Nada no Drive com esse nome. Se o usuário quiser o padrão de uma peça "
                "anterior, peça a pasta ou o nome do arquivo."
            )

        if len(linhas) == 1:
            linhas.append("Condomínio cadastrado, mas ainda sem histórico no Hub nem no Drive.")
        return "\n".join(linhas)[:_LIMITE]

    return {"dossie_da_demanda": dossie}
