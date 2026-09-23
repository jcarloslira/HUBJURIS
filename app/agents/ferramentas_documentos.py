"""Ferramentas de documento: revisar contrato em Word com controle de alterações.

O fluxo do escritório é este: chega o contrato do cliente em .docx, o advogado
pede a análise e recebe **o mesmo arquivo de volta**, com o que foi cortado,
reescrito e acrescentado marcado — para abrir no Word, conferir mudança a mudança
e clicar em "Aceitar todas". Entregar texto novo não serve: perde a formatação e
esconde o que mudou.

Aqui o modelo decide as alterações (por parágrafo, pelo número que ele vê) e o
``docx_revisao`` aplica no arquivo original.
"""

import json
import re
from base64 import b64decode
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic

from app.schemas.chat import AnexoIn
from app.services.arquivos import ArquivoGerado, CofreArquivos
from app.services.docx_revisao import (
    DocxRevisaoError,
    alteracoes_do_modelo,
    aplicar_revisao,
    ler_paragrafos,
)

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# Revisar contrato é trabalho de redação com regra fixa: não exige o Opus.
MODELO_REVISAO = "claude-sonnet-5"
_MAX_TOKENS = 16_000
_TIMEOUT_S = 300.0
# Parágrafo gigante estoura o pedido; o contrato inteiro cabe bem nisto.
_MAX_CHARS_DOCUMENTO = 120_000
_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

FERRAMENTAS_DOCUMENTOS: list[dict[str, Any]] = [
    {
        "name": "revisar_contrato_word",
        "description": (
            "Revisa o contrato .docx ANEXADO nesta conversa e devolve o MESMO arquivo "
            "com controle de alterações do Word (o que foi excluído, reescrito e "
            "acrescentado fica marcado; o usuário clica em 'Aceitar todas' e está "
            "pronto). Use sempre que o usuário anexar um contrato/minuta e pedir "
            "revisão, ajuste, adequação ao padrão do escritório ou proteção de "
            "cláusulas. Depois de chamar, explique no chat os principais riscos e "
            "mudanças — o arquivo já vai anexado à sua resposta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrucoes": {
                    "type": "string",
                    "description": (
                        "O que o usuário quer na revisão (ex.: proteger a CONTRATANTE, "
                        "reduzir multa, incluir foro de Brasília). Se ele não detalhar, "
                        "descreva o padrão de proteção do escritório."
                    ),
                },
                "parte_defendida": {
                    "type": "string",
                    "description": "Quem o escritório defende no contrato (ex.: o condomínio).",
                },
            },
            "required": ["instrucoes"],
        },
    }
]

NOMES_DOCUMENTOS = {f["name"] for f in FERRAMENTAS_DOCUMENTOS}

_PROMPT = """Você é o advogado revisor de contratos do escritório. Recebe um contrato
parágrafo a parágrafo, NUMERADO, e devolve as alterações a fazer.

Devolva APENAS um JSON:

{"resumo": "2 a 5 linhas: os riscos achados e o que você mudou",
 "alteracoes": [
   {"tipo": "substituir", "indice": 12, "texto": "nova redação COMPLETA do parágrafo"},
   {"tipo": "remover", "indice": 15},
   {"tipo": "inserir", "indice": 15, "texto": "texto do parágrafo novo, que entra DEPOIS do 15"}
 ]}

Regras:
- "indice" é o número que aparece entre colchetes antes do parágrafo. Nunca invente índice.
- Em "substituir", escreva o parágrafo inteiro já corrigido, não só o trecho — mas
  MUDE O MÍNIMO necessário: o que não tem problema fica palavra por palavra como está,
  porque cada diferença vira uma marca de revisão para o advogado conferir.
- Mexa só no que tem consequência jurídica: risco, prazo, multa, responsabilidade,
  rescisão, reajuste, foro, garantia, confidencialidade, dado pessoal. Não reescreva
  por estilo, não renumere cláusulas, não mexa em qualificação das partes.
- Nunca invente valor, data, nome ou número de cláusula.
- Se o contrato já estiver adequado num ponto, não altere.
- Só o JSON, sem crases e sem comentário."""


def _ultimo_docx(anexos: list[AnexoIn]) -> AnexoIn | None:
    """O .docx mais recente anexado — é nele que a revisão é aplicada."""
    for anexo in reversed(anexos or []):
        nome = (anexo.nome or "").lower()
        if nome.endswith(".docx") or anexo.tipo == _MIME_DOCX:
            return anexo
    return None


def _documento_numerado(paragrafos: list[str]) -> str:
    """O contrato como o modelo vê: um parágrafo por linha, com o índice na frente."""
    linhas = [f"[{i}] {texto}" for i, texto in enumerate(paragrafos) if texto.strip()]
    texto = "\n".join(linhas)
    return texto[:_MAX_CHARS_DOCUMENTO]


def _nome_revisado(nome: str) -> str:
    base = re.sub(r"\.docx$", "", nome, flags=re.IGNORECASE) or "contrato"
    return f"{base} (revisado).docx"


def montar_handlers_documentos(
    client: AsyncAnthropic,
    cofre: CofreArquivos,
    *,
    anexos: list[AnexoIn],
    escritorio_id: str,
    escritorio_nome: str = "",
    diretrizes: str = "",
) -> dict[str, Handler]:
    """Handlers das ferramentas de documento, presos aos anexos desta mensagem."""

    async def revisar(entrada: dict[str, Any]) -> str:
        anexo = _ultimo_docx(anexos)
        if anexo is None:
            return (
                "Não há contrato em Word nesta conversa. Peça ao usuário para anexar o "
                ".docx original — a revisão é feita EM CIMA do arquivo dele, para o "
                "controle de alterações mostrar o que mudou."
            )
        try:
            original = b64decode(anexo.dados)
            paragrafos = ler_paragrafos(original)
        except (DocxRevisaoError, ValueError) as exc:
            return f"Não consegui abrir o arquivo '{anexo.nome}': {exc}"
        if not any(p.strip() for p in paragrafos):
            return f"O arquivo '{anexo.nome}' não tem texto para revisar."

        pedido = [
            f"CONTRATO ({len(paragrafos)} parágrafos):\n\n{_documento_numerado(paragrafos)}",
            f"PARTE DEFENDIDA: {entrada.get('parte_defendida') or 'não informada'}",
            "O QUE O USUÁRIO PEDIU:\n"
            + str(entrada.get("instrucoes") or "revisão padrão do escritório"),
        ]
        if diretrizes.strip():
            pedido.insert(1, f"COMO ESTE ESCRITÓRIO TRABALHA:\n{diretrizes.strip()}")

        resiliente = client.with_options(timeout=_TIMEOUT_S, max_retries=2)
        resposta = await resiliente.messages.create(
            model=MODELO_REVISAO,
            max_tokens=_MAX_TOKENS,
            system=_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(pedido)}],
        )
        bruto = "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")
        achado = re.search(r"\{.*\}", bruto, re.S)
        if not achado:
            return "A revisão não voltou no formato esperado. Tente pedir de novo."
        try:
            dados = json.loads(achado.group(0))
        except json.JSONDecodeError:
            return "A revisão não voltou no formato esperado. Tente pedir de novo."

        alteracoes = alteracoes_do_modelo(dados)
        if not alteracoes:
            return (
                "Li o contrato inteiro e não encontrei cláusula que justifique alteração. "
                f"Resumo da análise: {dados.get('resumo') or 'contrato adequado'}"
            )
        try:
            revisado, aplicadas = aplicar_revisao(
                original, alteracoes, autor=escritorio_nome or "LexHub"
            )
        except DocxRevisaoError as exc:
            return f"Não consegui gravar a revisão no arquivo: {exc}"

        identificador = cofre.guardar(
            ArquivoGerado(
                nome=_nome_revisado(anexo.nome),
                tipo=_MIME_DOCX,
                dados=revisado,
                escritorio_id=escritorio_id,
            )
        )
        return (
            f"Contrato revisado com {aplicadas} alterações marcadas no controle de "
            f"alterações do Word.\nResumo da análise: {dados.get('resumo') or ''}\n"
            f"ENTREGUE O ARQUIVO ao usuário colando esta linha, sozinha, ao final da sua "
            f'resposta: [[ARQUIVO id="{identificador}" nome="{_nome_revisado(anexo.nome)}"]]'
        )

    return {"revisar_contrato_word": revisar}
