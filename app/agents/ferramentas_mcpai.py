"""Ferramentas dos agentes sobre o mcp.ai ("Banco MCP"): EasyJur e Tiflux.

Conjunto CURADO: consultas ao sistema jurídico (EasyJur — processos, partes,
movimentações, financeiro, clientes, agenda) e ao helpdesk (Tiflux — clientes e
tickets). LEITURA é autônoma; ESCRITA (abrir/responder ticket) é propor-e-confirmar.

Varreduras grandes rodam AQUI, no servidor: o agente pede "processos distribuídos
em agosto" e recebe só os que batem, com um resumo. Passar milhares de registros
pelo contexto do modelo estoura o orçamento de resposta — e foi assim que
contagens saíam menores que as reais.

Contrato das APIs, descoberto quebrando:
- EasyJur pagina com ``page``/``page_size`` e aceita NO MÁXIMO 100 por página
  (acima disso responde 422 e a consulta inteira falha).
- Tiflux pagina com ``limit`` (máx. 200) e ``offset``, que é o NÚMERO DA PÁGINA
  (1, 2, 3…), não a posição do registro. A lista vem em ``value`` e o total em
  ``total_items``; sem ``filter_by`` a API devolve só os tickets em aberto.
"""

import asyncio
import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.mcpai import MCPAIClient, MCPAIError

# Chars devolvidos ao modelo por chamada.
_LIMITE_RESULTADO = 16_000
# Alguns andamentos trazem log de acordo com ~3.000 chars; o que importa (data +
# o que aconteceu) está sempre no começo.
_LIMITE_ANDAMENTO = 400

_EASYJUR_PAGE_MAX = 100
_TIFLUX_LIMIT_MAX = 200
# Teto da varredura de tickets: 5 páginas de 200. Acima disso o pedido está amplo
# demais para um relatório — o agente deve refinar por cliente ou período.
_TIFLUX_PAGINAS_MAX = 5
# Páginas buscadas em paralelo nas varreduras (4.800 processos = 49 páginas).
_CONCORRENCIA = 6

_ROTA_PROCESSOS = "/api/easyjur/list/processos"
_ROTA_TICKETS = "/api/tiflux/list/tickets"
_CAMPOS_DATA_PROCESSO = ("data_cadastro", "data_distribuicao", "data_encerramento")

Handler = Callable[[dict[str, Any]], Awaitable[str]]
Busca = Callable[[], Awaitable[Any]]

# Campos que valem a pena de cada PROCESSO (a API devolve ~80 por item).
_CAMPOS_PROCESSO = (
    "id_processo",
    "numero",
    "titulo_acao",
    "nome_contrario",
    "vinculo",
    "status_label",
    "instancia_label",
    "valor_causa",
    "vara",
    "uf",
    "fase_atual",
    "data_distribuicao",
    "ultimo_andamento",
)
# Na listagem por período, cada item é enxuto de propósito: a lista inteira precisa
# caber em uma resposta, e o andamento completo se consulta processo a processo.
_CAMPOS_PROCESSO_LISTA = (
    "numero",
    "titulo_acao",
    "nome_contrario",
    "status_label",
    "valor_causa",
    "vara",
    "uf",
    "fase_atual",
)
_ANDAMENTO_NA_LISTA = 140
# Campos úteis de cada TICKET do Tiflux (a API manda 21).
_CAMPOS_TICKET = (
    "ticket_number",
    "title",
    "client",
    "requestor",
    "responsible",
    "desk",
    "stage",
    "status",
    "priority",
    "created_at",
    "updated_at",
)
# Campos úteis de cada PESSOA do EasyJur.
_CAMPOS_PESSOA = ("id", "nome", "apelido", "fisica_juridica", "cpf", "cnpj", "email", "celular")

_ENTIDADES_HTML = (
    ("&nbsp;", " "),
    ("&ccedil;", "ç"),
    ("&atilde;", "ã"),
    ("&aacute;", "á"),
    ("&eacute;", "é"),
    ("&iacute;", "í"),
    ("&oacute;", "ó"),
    ("&uacute;", "ú"),
    ("&ecirc;", "ê"),
    ("&ocirc;", "ô"),
    ("&deg;", "º"),
    ("&amp;", "&"),
)


def _limpar_html(valor: Any) -> Any:
    """Remove tags e desescapa entidades HTML de um texto (ex.: último andamento)."""
    if not isinstance(valor, str):
        return valor
    texto = re.sub(r"<[^>]+>", " ", valor)
    for entidade, caractere in _ENTIDADES_HTML:
        texto = texto.replace(entidade, caractere)
    return re.sub(r"\s+", " ", texto).strip()


def _achatar(valor: Any) -> Any:
    """Reduz os objetos {id, name} ao nome — o id não diz nada a quem lê."""
    if isinstance(valor, dict):
        return valor.get("name") or valor.get("nome") or valor
    return valor


def _vazio(valor: Any) -> bool:
    return valor is None or valor == "" or valor == 0 or valor == [] or valor == {}


def _enxugar_processo(item: dict[str, Any]) -> dict[str, Any]:
    """Projeta um processo nos campos essenciais, com cliente e área legíveis."""
    linha = {c: item.get(c) for c in _CAMPOS_PROCESSO if not _vazio(item.get(c))}
    cliente = _achatar(item.get("cliente_info")) or item.get("nome_cliente")
    if cliente:
        linha["cliente"] = cliente
    area = _achatar(item.get("area_info"))
    if area:
        linha["area"] = area
    # "comarca" vem como código interno (ex.: "5599"); o nome está em comarca_info.
    comarca = _achatar(item.get("comarca_info"))
    if isinstance(comarca, str) and comarca:
        linha["comarca"] = comarca
    if "ultimo_andamento" in linha:
        andamento = _limpar_html(linha["ultimo_andamento"])
        if len(andamento) > _LIMITE_ANDAMENTO:
            andamento = andamento[:_LIMITE_ANDAMENTO] + " […]"
        linha["ultimo_andamento"] = andamento
    return linha


def _enxugar_processo_lista(item: dict[str, Any], campo_data: str) -> dict[str, Any]:
    """Versão compacta para listagens longas: identifica o processo e o momento dele."""
    linha: dict[str, Any] = {"id_processo": item.get("id_processo")}
    if item.get(campo_data):
        linha[campo_data] = str(item[campo_data])[:10]
    cliente = _achatar(item.get("cliente_info")) or item.get("nome_cliente")
    if cliente:
        linha["cliente"] = cliente
    linha.update(
        {c: item.get(c) for c in _CAMPOS_PROCESSO_LISTA if not _vazio(item.get(c))}
    )
    andamento = _limpar_html(item.get("ultimo_andamento") or "")
    if andamento:
        if len(andamento) > _ANDAMENTO_NA_LISTA:
            andamento = andamento[:_ANDAMENTO_NA_LISTA] + " […]"
        linha["ultimo_andamento"] = andamento
    return linha


def _enxugar_ticket(item: dict[str, Any]) -> dict[str, Any]:
    """Projeta um ticket nos campos essenciais, com prazo de SLA quando houver."""
    linha = {c: _achatar(item.get(c)) for c in _CAMPOS_TICKET if not _vazio(item.get(c))}
    if "is_closed" in item:
        linha["is_closed"] = bool(item["is_closed"])
    sla = item.get("sla_info")
    if isinstance(sla, dict):
        if sla.get("solve_expiration"):
            linha["sla_vence"] = sla["solve_expiration"]
        if sla.get("solved_in_time") is not None:
            linha["resolvido_no_prazo"] = sla["solved_in_time"]
    return linha


def _enxugar_cliente_tiflux(item: dict[str, Any]) -> dict[str, Any]:
    """Cliente do Tiflux reduzido a id, nome e CNPJ (o que liga ao EasyJur)."""
    linha: dict[str, Any] = {"id": item.get("id"), "nome": item.get("name")}
    if item.get("social_revenue"):
        linha["cnpj"] = item["social_revenue"]
    if item.get("status") is False:
        linha["inativo"] = True
    return linha


def _enxugar(path: str, resultado: Any) -> Any:
    """Enxuga a resposta: remove ``raw_data`` (duplica tudo) e projeta cada item nos
    campos essenciais, preservando os totais para o agente saber quanto falta."""
    if not isinstance(resultado, dict):
        return resultado
    resultado = {k: v for k, v in resultado.items() if k != "raw_data"}

    # O Tiflux usa "value"/"total_items"; o EasyJur, "data"/"meta".
    lista_tiflux = resultado.get("value")
    if isinstance(lista_tiflux, list):
        if "tickets" in path:
            resultado["value"] = [_enxugar_ticket(t) for t in lista_tiflux if isinstance(t, dict)]
        elif "clients" in path:
            resultado["value"] = [
                _enxugar_cliente_tiflux(c) for c in lista_tiflux if isinstance(c, dict)
            ]
        return resultado

    itens = resultado.get("data")
    if isinstance(itens, list) and itens and isinstance(itens[0], dict):
        if "processos" in path:
            resultado["data"] = [_enxugar_processo(p) for p in itens]
        elif "pessoas" in path:
            resultado["data"] = [
                {c: p.get(c) for c in _CAMPOS_PESSOA if not _vazio(p.get(c))} for p in itens
            ]
    return resultado


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _serializar(obj: Any) -> str:
    """Serializa dentro do orçamento cortando ITENS do fim da lista — nunca o texto
    no meio, que entregava JSON quebrado e fazia o agente achar que tinha visto tudo.
    Quando corta, diz explicitamente quantos ficaram de fora."""
    texto = _json(obj)
    if len(texto) <= _LIMITE_RESULTADO:
        return texto
    chave = None
    if isinstance(obj, dict):
        chave = next((k for k in ("data", "value") if isinstance(obj.get(k), list)), None)
    if chave is None:
        return texto[:_LIMITE_RESULTADO] + " …[resposta cortada pelo limite de contexto]"

    lista = obj[chave]
    baixo, alto = 0, len(lista)
    while baixo < alto:  # maior prefixo da lista que cabe, com folga para o aviso
        meio = (baixo + alto + 1) // 2
        if len(_json({**obj, chave: lista[:meio]})) <= _LIMITE_RESULTADO - 400:
            baixo = meio
        else:
            alto = meio - 1
    aviso = (
        f"Mostrando {baixo} de {len(lista)} itens desta resposta (limite de contexto). "
        "Os demais existem: peça a próxima página, uma página menor ou refine o filtro. "
        "Não conclua contagens a partir desta lista — use os totais e o resumo."
    )
    return _json({**obj, chave: lista[:baixo], "_aviso": aviso})


def _inteiro(valor: Any, padrao: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _normalizar_args(path: str, entrada: dict[str, Any]) -> dict[str, Any]:
    """Aplica os limites reais das APIs, seja lá o que o modelo pedir."""
    args = {k: v for k, v in entrada.items() if v is not None and v != ""}
    if path.startswith("/api/easyjur/list/") and "page_size" in args:
        args["page_size"] = max(1, min(_inteiro(args["page_size"], 20), _EASYJUR_PAGE_MAX))
    if path.startswith("/api/tiflux/list/"):
        if "limit" in args:
            args["limit"] = max(1, min(_inteiro(args["limit"], 50), _TIFLUX_LIMIT_MAX))
        if "offset" in args:
            args["offset"] = max(1, _inteiro(args["offset"], 1))
        if "client_ids" in args:
            ids = args["client_ids"]
            ids = ids if isinstance(ids, list) else [ids]
            args["client_ids"] = [str(i) for i in ids]
    return args


def _data_iso(valor: Any) -> str | None:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA e devolve AAAA-MM-DD (comparável como texto)."""
    texto = str(valor or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        return texto
    achado = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if achado:
        dia, mes, ano = achado.groups()
        return f"{ano}-{mes}-{dia}"
    return None


async def _em_paralelo(tarefas: list[Busca]) -> tuple[list[Any], int]:
    """Roda as buscas com concorrência limitada; devolve (resultados, falhas)."""
    semaforo = asyncio.Semaphore(_CONCORRENCIA)

    async def com_limite(tarefa: Busca) -> Any:
        async with semaforo:
            return await tarefa()

    brutos = await asyncio.gather(*(com_limite(t) for t in tarefas), return_exceptions=True)
    ok = [b for b in brutos if not isinstance(b, BaseException)]
    return ok, len(brutos) - len(ok)


async def _varrer_processos(
    client: MCPAIClient, filtros: dict[str, Any]
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Busca todas as páginas de processos em paralelo.

    Returns:
        (processos únicos, total informado pela API, páginas, páginas que falharam).
    """
    primeira = await client.chamar(
        _ROTA_PROCESSOS, {**filtros, "page": 1, "page_size": _EASYJUR_PAGE_MAX}
    )
    meta = primeira.get("meta") or {}
    total_paginas = max(1, _inteiro(meta.get("total_pages"), 1))
    itens: list[dict[str, Any]] = list(primeira.get("data") or [])

    def pagina(numero: int) -> Busca:
        async def buscar() -> list[dict[str, Any]]:
            args = {**filtros, "page": numero, "page_size": _EASYJUR_PAGE_MAX}
            return (await client.chamar(_ROTA_PROCESSOS, args)).get("data") or []

        return buscar

    lotes, falhas = await _em_paralelo([pagina(n) for n in range(2, total_paginas + 1)])
    for lote in lotes:
        itens.extend(lote)

    unicos: dict[Any, dict[str, Any]] = {}
    for indice, processo in enumerate(itens):
        unicos.setdefault(processo.get("id_processo") or f"sem-id-{indice}", processo)
    total = _inteiro(meta.get("total"), len(unicos))
    return list(unicos.values()), total, total_paginas, falhas


async def _processos_por_periodo(
    client: MCPAIClient, entrada: dict[str, Any], cache: dict[Any, Any]
) -> str:
    """Varre TODAS as páginas de processos no servidor e devolve só os do período.

    A varredura (~10s para 4.800 processos) fica guardada durante o turno: pedir a
    página 2 da lista não refaz as 49 chamadas ao EasyJur.
    """
    inicio = _data_iso(entrada.get("data_inicio"))
    fim = _data_iso(entrada.get("data_fim"))
    if not inicio or not fim:
        return "Informe data_inicio e data_fim no formato AAAA-MM-DD ou DD/MM/AAAA."
    campo = entrada.get("campo")
    if campo not in _CAMPOS_DATA_PROCESSO:
        campo = "data_distribuicao"
    filtros = _normalizar_args(
        _ROTA_PROCESSOS,
        {
            k: entrada.get(k)
            for k in ("id_cliente", "uf", "status", "nome_parte", "advogado_nome", "comarca")
        },
    )

    chave = ("varredura_processos", tuple(sorted(filtros.items())))
    if chave not in cache:
        cache[chave] = await _varrer_processos(client, filtros)
    processos, total, total_paginas, falhas = cache[chave]

    casados = [p for p in processos if inicio <= str(p.get(campo) or "")[:10] <= fim]
    casados.sort(key=lambda p: str(p.get(campo) or ""))
    lista = [_enxugar_processo_lista(p, campo) for p in casados]

    resumo: dict[str, Any] = {
        "periodo": f"{inicio} a {fim}",
        "filtrado_por": campo,
        "processos_varridos": len(processos),
        "total_no_easyjur": total,
        "encontrados": len(casados),
        "valor_total_das_causas": round(sum(float(p.get("valor_causa") or 0) for p in casados), 2),
        "por_uf": dict(Counter(p.get("uf") or "não informado" for p in casados).most_common()),
        "por_cliente": dict(
            Counter(p.get("cliente") or "não informado" for p in lista).most_common(20)
        ),
    }
    if falhas:
        resumo["aviso"] = (
            f"{falhas} de {total_paginas} páginas falharam na varredura — o resultado pode "
            "estar incompleto. Diga isso ao usuário."
        )

    # Cada resposta leva o máximo de itens que cabe e diz de onde continuar. Página de
    # tamanho fixo não serve: processos têm tamanhos diferentes, e o que não coubesse
    # sumiria entre uma página e a seguinte.
    primeiro = max(1, min(_inteiro(entrada.get("a_partir_de"), 1), max(1, len(lista))))
    restantes = lista[primeiro - 1 :]

    def montar(quantos: int) -> dict[str, Any]:
        ultimo = primeiro - 1 + quantos
        extra: dict[str, Any] = {"itens_nesta_resposta": f"{primeiro} a {ultimo} de {len(lista)}"}
        if ultimo < len(lista):
            extra["proxima"] = (
                f"Faltam {len(lista) - ultimo} processos da lista. Chame de novo com os mesmos "
                f"parâmetros e a_partir_de={ultimo + 1} (é instantâneo, não varre de novo)."
            )
        return {"resumo": {**resumo, **extra}, "data": restantes[:quantos]}

    baixo, alto = 0, len(restantes)
    while baixo < alto:  # maior quantidade de itens que cabe na resposta
        meio = (baixo + alto + 1) // 2
        if len(_json(montar(meio))) <= _LIMITE_RESULTADO:
            baixo = meio
        else:
            alto = meio - 1
    return _json(montar(baixo))


async def _tickets(client: MCPAIClient, entrada: dict[str, Any], _cache: dict[Any, Any]) -> str:
    """Lista tickets do Tiflux com filtros; com ``todas_paginas`` varre no servidor."""
    todas = bool(entrada.get("todas_paginas"))
    args = _normalizar_args(
        _ROTA_TICKETS, {k: v for k, v in entrada.items() if k != "todas_paginas"}
    )
    args.setdefault("limit", _TIFLUX_LIMIT_MAX if todas else 50)
    args.setdefault("offset", 1)

    primeira = await client.chamar(_ROTA_TICKETS, args)
    total = _inteiro(primeira.get("total_items"), 0)
    tickets: list[dict[str, Any]] = list(primeira.get("value") or [])
    falhas = 0

    if todas and total > len(tickets):
        paginas = min(math.ceil(total / args["limit"]), _TIFLUX_PAGINAS_MAX)

        def pagina(numero: int) -> Busca:
            async def buscar() -> list[dict[str, Any]]:
                resposta = await client.chamar(_ROTA_TICKETS, {**args, "offset": numero})
                return resposta.get("value") or []

            return buscar

        seguintes = range(args["offset"] + 1, args["offset"] + paginas)
        lotes, falhas = await _em_paralelo([pagina(n) for n in seguintes])
        for lote in lotes:
            tickets.extend(lote)

    enxutos = [_enxugar_ticket(t) for t in tickets if isinstance(t, dict)]
    resumo: dict[str, Any] = {
        "total_items": total,
        "recebidos_nesta_resposta": len(enxutos),
        "abertos": sum(1 for t in enxutos if not t.get("is_closed")),
        "fechados": sum(1 for t in enxutos if t.get("is_closed")),
        "por_estagio": dict(Counter(t.get("stage") or "?" for t in enxutos).most_common()),
        "por_responsavel": dict(
            Counter(t.get("responsible") or "sem responsável" for t in enxutos).most_common(15)
        ),
        "por_cliente": dict(Counter(t.get("client") or "?" for t in enxutos).most_common(15)),
        "por_mesa": dict(Counter(t.get("desk") or "?" for t in enxutos).most_common(10)),
    }
    if total > len(enxutos):
        resumo["aviso"] = (
            f"Esta resposta traz {len(enxutos)} de {total} tickets; os quadros acima valem só "
            "para eles. Use todas_paginas=true ou refine por client_ids/período antes de "
            "afirmar números."
        )
    if falhas:
        resumo["aviso_falhas"] = f"{falhas} página(s) falharam — resultado incompleto."
    return _serializar({"resumo": resumo, "value": enxutos})


# name -> path, escrita, descrição, propriedades, obrigatórios (e handler especial)
_CATALOGO: list[dict[str, Any]] = [
    # ── EasyJur — jurídico (somente leitura) ──────────────────────
    {
        "name": "easyjur_processos",
        "path": _ROTA_PROCESSOS,
        "escrita": False,
        "descricao": (
            "Lista/busca processos no EasyJur para navegar e ver detalhes. Filtros: "
            "id_cliente, numero, nome_parte, cpf, cnpj, advogado_nome, status, comarca, uf, "
            "movimentacao, dias_movimentacao. page_size aceita NO MÁXIMO 100. Para perguntas "
            "sobre um PERÍODO (distribuídos, cadastrados ou encerrados entre duas datas) NÃO "
            "pagine por aqui: use easyjur_processos_por_periodo, que varre tudo no servidor. "
            "Confira 'meta.total' antes de afirmar quantos existem."
        ),
        "props": {
            "id_cliente": {
                "type": "integer",
                "description": "Filtra os processos deste cliente (id de easyjur_clientes).",
            },
            "numero": {"type": "string", "description": "Número do processo (CNJ ou interno)."},
            "nome_parte": {"type": "string", "description": "Nome da parte."},
            "cpf": {"type": "string", "description": "CPF da parte."},
            "cnpj": {"type": "string", "description": "CNPJ da parte."},
            "advogado_nome": {"type": "string", "description": "Advogado responsável."},
            "status": {"type": "string", "description": "Situação do processo (ex.: Ativo)."},
            "comarca": {"type": "string", "description": "Comarca."},
            "uf": {"type": "string", "description": "UF (ex.: DF, GO)."},
            "movimentacao": {"type": "string", "description": "Texto do andamento."},
            "dias_movimentacao": {
                "type": "integer",
                "description": "Movimentados nos últimos N dias.",
            },
            "page": {"type": "integer", "description": "Página (padrão 1)."},
            "page_size": {"type": "integer", "description": "Por página, máximo 100."},
        },
        "obrig": [],
    },
    {
        "name": "easyjur_processos_por_periodo",
        "path": _ROTA_PROCESSOS,
        "escrita": False,
        "especial": _processos_por_periodo,
        "descricao": (
            "Lista os processos cuja data (distribuição, cadastro ou encerramento) cai entre "
            "data_inicio e data_fim — ex.: 'processos distribuídos em agosto/2026'. O servidor "
            "varre TODOS os processos do escritório e devolve só os que batem, com um resumo "
            "(quantidade, valor total das causas, divisão por UF e por cliente). Use SEMPRE que "
            "a pergunta envolver período; é exato e rápido. Pode combinar com id_cliente, uf, "
            "status, nome_parte, advogado_nome ou comarca."
        ),
        "props": {
            "data_inicio": {"type": "string", "description": "Início, AAAA-MM-DD."},
            "data_fim": {"type": "string", "description": "Fim (inclusive), AAAA-MM-DD."},
            "campo": {
                "type": "string",
                "enum": list(_CAMPOS_DATA_PROCESSO),
                "description": "Qual data filtrar; padrão data_distribuicao.",
            },
            "id_cliente": {"type": "integer", "description": "Restringe a um cliente."},
            "uf": {"type": "string", "description": "Restringe a uma UF."},
            "status": {"type": "string", "description": "Restringe à situação (ex.: Ativo)."},
            "nome_parte": {"type": "string", "description": "Restringe a uma parte."},
            "advogado_nome": {"type": "string", "description": "Restringe a um advogado."},
            "comarca": {"type": "string", "description": "Restringe a uma comarca."},
            "a_partir_de": {
                "type": "integer",
                "description": "Continua a LISTA a partir deste item (indicado em 'proxima'); "
                "o resumo sempre cobre tudo.",
            },
        },
        "obrig": ["data_inicio", "data_fim"],
    },
    {
        "name": "easyjur_processo",
        "path": "/api/easyjur/get/processo",
        "escrita": False,
        "descricao": "Detalha um processo do EasyJur pelo seu id.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_partes",
        "path": "/api/easyjur/processo/partes",
        "escrita": False,
        "descricao": "Partes (autor, réu, terceiros) de um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_movimentacoes",
        "path": "/api/easyjur/processo/mensagens",
        "escrita": False,
        "descricao": "Movimentações/andamentos e mensagens de um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_processo_financeiro",
        "path": "/api/easyjur/processo/financeiros",
        "escrita": False,
        "descricao": "Lançamentos financeiros vinculados a um processo do EasyJur.",
        "props": {"processo_id": {"type": "integer", "description": "id do processo."}},
        "obrig": ["processo_id"],
    },
    {
        "name": "easyjur_clientes",
        "path": "/api/easyjur/list/pessoas",
        "escrita": False,
        "descricao": (
            "Busca pessoas/clientes no EasyJur (condomínios, síndicos, contrários). Passe 'nome' "
            "para FILTRAR (ex.: 'Casablanca') — sem filtro vem só a 1ª página. Retorna o id do "
            "cliente, usado em easyjur_processos(id_cliente=...)."
        ),
        "props": {
            "nome": {
                "type": "string",
                "description": "Filtra clientes cujo nome contém este texto (ex.: 'Casablanca').",
            },
            "cpf": {"type": "string", "description": "CPF da pessoa."},
            "cnpj": {"type": "string", "description": "CNPJ da pessoa."},
            "page": {"type": "integer", "description": "Página (padrão 1)."},
            "page_size": {"type": "integer", "description": "Por página, máximo 100."},
        },
        "obrig": [],
    },
    {
        "name": "easyjur_cliente",
        "path": "/api/easyjur/get/pessoa",
        "escrita": False,
        "descricao": "Detalha uma pessoa/cliente do EasyJur pelo id.",
        "props": {"pessoa_id": {"type": "integer", "description": "id da pessoa."}},
        "obrig": ["pessoa_id"],
    },
    {
        "name": "easyjur_agenda",
        "path": "/api/easyjur/list/agenda",
        "escrita": False,
        "descricao": "Lista compromissos/prazos da agenda do EasyJur.",
        "props": {},
        "obrig": [],
    },
    # ── Tiflux — helpdesk (leitura) ───────────────────────────────
    {
        "name": "tiflux_clientes",
        "path": "/api/tiflux/list/clients",
        "escrita": False,
        "descricao": (
            "Busca clientes no Tiflux pelo nome e devolve o id — é o id que filtra os tickets "
            "em tiflux_tickets(client_ids=[...]). Use antes de listar tickets de um condomínio."
        ),
        "props": {
            "name": {"type": "string", "description": "Parte do nome (ex.: 'SQB')."},
            "limit": {"type": "integer", "description": "Por página, máximo 200."},
            "offset": {"type": "integer", "description": "NÚMERO DA PÁGINA, começando em 1."},
        },
        "obrig": [],
    },
    {
        "name": "tiflux_tickets",
        "path": _ROTA_TICKETS,
        "escrita": False,
        "especial": _tickets,
        "descricao": (
            "Lista chamados do Tiflux e devolve um resumo pronto (abertos/fechados, por "
            "estágio, responsável, cliente e mesa). ATENÇÃO: sem filter_by a API traz só os "
            "ABERTOS — para relatório de período use filter_by='all'. Para um condomínio, "
            "pegue o id em tiflux_clientes e passe client_ids. Para cobrir tudo passe "
            "todas_paginas=true (o servidor varre até 1.000 tickets). 'total_items' é o total "
            "real do filtro: nunca afirme números a partir de uma página parcial."
        ),
        "props": {
            "client_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "ids de cliente (de tiflux_clientes).",
            },
            "filter_by": {
                "type": "string",
                "enum": ["open", "closed", "canceled", "all"],
                "description": "Situação; a API assume 'open' se omitido.",
            },
            "start_datetime": {
                "type": "string",
                "description": "Início do período, ISO (ex.: 2026-08-01T00:00:00Z).",
            },
            "end_datetime": {
                "type": "string",
                "description": "Fim do período, ISO (ex.: 2026-08-31T23:59:59Z).",
            },
            "todas_paginas": {
                "type": "boolean",
                "description": "Varre todas as páginas no servidor (até 1.000 tickets).",
            },
            "limit": {"type": "integer", "description": "Por página, máximo 200."},
            "offset": {"type": "integer", "description": "NÚMERO DA PÁGINA, começando em 1."},
        },
        "obrig": [],
    },
    {
        "name": "tiflux_ticket_respostas",
        "path": "/api/tiflux/list/ticket/answers",
        "escrita": False,
        "descricao": "Respostas/histórico de um ticket do Tiflux.",
        "props": {"ticket_number": {"type": "integer", "description": "número do ticket."}},
        "obrig": ["ticket_number"],
    },
    # ── Tiflux — helpdesk (escrita: propor-e-confirmar) ───────────
    {
        "name": "tiflux_criar_ticket",
        "path": "/api/tiflux/create/ticket",
        "escrita": True,
        "descricao": (
            "Abre um ticket/chamado no Tiflux. AÇÃO EXTERNA: proponha e peça confirmação "
            "ao usuário ANTES de chamar."
        ),
        "props": {
            "title": {"type": "string", "description": "Título do chamado."},
            "description": {"type": "string", "description": "Descrição do chamado."},
        },
        "obrig": ["title", "description"],
    },
    {
        "name": "tiflux_responder_ticket",
        "path": "/api/tiflux/create/ticket/answer",
        "escrita": True,
        "descricao": (
            "Responde um ticket do Tiflux. AÇÃO EXTERNA: proponha e peça confirmação antes."
        ),
        "props": {
            "ticket_number": {"type": "integer", "description": "número do ticket."},
            "text": {"type": "string", "description": "Texto da resposta."},
        },
        "obrig": ["ticket_number", "text"],
    },
]

# Schemas expostos ao modelo (formato tool-use da Anthropic).
FERRAMENTAS_MCPAI: list[dict[str, Any]] = [
    {
        "name": t["name"],
        "description": t["descricao"],
        "input_schema": {
            "type": "object",
            "properties": t["props"],
            "required": t["obrig"],
        },
    }
    for t in _CATALOGO
]

NOMES_MCPAI = {t["name"] for t in _CATALOGO}
_ROTA: dict[str, str] = {t["name"]: t["path"] for t in _CATALOGO}


def _sistema(nome: str) -> str:
    return "EasyJur" if nome.startswith("easyjur") else "Tiflux"


def montar_handlers_mcpai(client: MCPAIClient) -> dict[str, Handler]:
    """Handlers das ferramentas mcp.ai, ligados ao cliente REST configurado.

    Os handlers são montados a cada turno de conversa, então o cache abaixo vive
    exatamente um turno: o bastante para o agente paginar uma varredura sem
    refazê-la, curto o bastante para nunca servir dado velho.
    """
    cache: dict[Any, Any] = {}

    def _fazer(ferramenta: dict[str, Any]) -> Handler:
        nome, path = ferramenta["name"], ferramenta["path"]
        especial = ferramenta.get("especial")

        async def handler(entrada: dict[str, Any]) -> str:
            try:
                if especial is not None:
                    return await especial(client, dict(entrada), cache)
                resultado = await client.chamar(path, _normalizar_args(path, dict(entrada)))
            except MCPAIError as exc:
                return f"Não consegui consultar o {_sistema(nome)} agora ({exc})."
            return _serializar(_enxugar(path, resultado))

        return handler

    return {t["name"]: _fazer(t) for t in _CATALOGO}
