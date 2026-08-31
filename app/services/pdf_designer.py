"""Gerador de PDF "desenhado" — o modelo escreve o HTML, o WeasyPrint renderiza.

Os relatórios que o escritório já aprovou foram produzidos por **WeasyPrint 69.0**
(está gravado nos metadados dos PDFs). Ou seja: o modelo não desenha PDF por
coordenadas — ele escreve HTML + CSS e um renderizador transforma em papel.

A primeira versão deste módulo delegava tudo à Agent Skill ``pdf`` da Anthropic,
que roda o mesmo WeasyPrint dentro de um sandbox. Funcionava, mas o modelo ficava
num laço de *renderiza → abre → confere → corrige* e a geração passava de 20
minutos a ~R$ 4 por peça. Trazendo a renderização para cá, a mesma peça sai em
~70 segundos por ~R$ 0,50, com o mesmo motor e as mesmas fontes.
"""

import base64
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.services.design_system import ESPECIFICACAO
from app.services.documentos import Timbre

# Escrever o HTML/CSS da peça não exige o raciocínio do Opus.
MODELO_PADRAO = "claude-sonnet-5"
_MAX_TOKENS = 32_000
# A geração leva ~1 minuto; damos folga para peças longas sem prender o worker.
_TIMEOUT_S = 300.0
_TENTATIVAS = 2
# O modelo referencia o logo por este marcador; trocamos pelo data URI depois,
# para não gastar milhares de tokens mandando a imagem em base64 no prompt.
_MARCADOR_LOGO = "__LOGO_DO_ESCRITORIO__"


class PDFDesignerError(Exception):
    """Falha ao gerar o PDF desenhado."""


_INSTRUCAO_SAIDA = (
    "Responda APENAS com o documento HTML completo (de <!doctype html> até "
    "</html>), com todo o CSS embutido em <style>. Sem crases, sem explicação "
    "antes ou depois."
)


def _bloco_timbre(timbre: Timbre) -> str:
    """Descreve a identidade do escritório, que se sobrepõe à paleta padrão."""
    linhas = ["IDENTIDADE DESTE ESCRITÓRIO (use exatamente estes dados):"]
    linhas.append(f"- Nome: {timbre.nome or 'não informado'}")
    if timbre.subtitulo:
        linhas.append(f"- Subtítulo/área de atuação: {timbre.subtitulo}")
    if timbre.cor:
        linhas.append(
            f"- Cor institucional: {timbre.cor} — use no lugar do petróleo escuro do "
            "sistema de design, mantendo o restante da paleta."
        )
    if timbre.rodape:
        linhas.append(f"- Rodapé (endereço/contato): {timbre.rodape}")
    if timbre.logo:
        linhas.append(
            f'- Logotipo: use exatamente <img src="{_MARCADOR_LOGO}" alt=""> na capa '
            "e no cabeçalho, com altura de ~48px. O src será substituído na entrega."
        )
    return "\n".join(linhas)


def _montar_prompt(titulo: str, conteudo: str, timbre: Timbre, instrucoes: str) -> str:
    """Junta sistema de design, identidade e conteúdo num único pedido."""
    partes = [
        "Você é o designer de documentos de um escritório de advocacia brasileiro. "
        "Produza a peça abaixo seguindo à risca o sistema de design do escritório — "
        "ele foi extraído de peças já aprovadas pelo sócio, então não improvise um "
        "visual próprio.",
        ESPECIFICACAO,
        _bloco_timbre(timbre),
        f"TÍTULO: {titulo}",
    ]
    if instrucoes.strip():
        partes.append(f"CONTEXTO E PEDIDOS DO USUÁRIO:\n{instrucoes.strip()}")
    partes.append(f"CONTEÚDO (Markdown):\n\n{conteudo}")
    partes.append(_INSTRUCAO_SAIDA)
    return "\n\n".join(partes)


def _limpar_html(bruto: str) -> str:
    """Tira cercas de markdown e preâmbulo que o modelo às vezes acrescenta."""
    texto = bruto.strip()
    texto = re.sub(r"^```(?:html)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    inicio = texto.lower().find("<!doctype")
    if inicio == -1:
        inicio = texto.lower().find("<html")
    return texto[inicio:].strip() if inicio > 0 else texto


def _mime_da_imagem(dados: bytes) -> str:
    """Detecta PNG/JPEG pelos bytes mágicos (o logo vem do banco sem mime)."""
    if dados.startswith(b"\x89PNG"):
        return "image/png"
    if dados.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "application/octet-stream"


def _aplicar_logo(html: str, logo: bytes | None) -> str:
    """Troca o marcador pelo data URI do logo (ou remove a tag se não houver)."""
    if not logo:
        limpo = html.replace(f'<img src="{_MARCADOR_LOGO}" alt="">', "")
        return limpo.replace(_MARCADOR_LOGO, "")
    uri = f"data:{_mime_da_imagem(logo)};base64,{base64.b64encode(logo).decode()}"
    return html.replace(_MARCADOR_LOGO, uri)


def renderizar_pdf(html: str) -> bytes:
    """Renderiza o HTML em PDF com o WeasyPrint (mesmo motor das peças aprovadas).

    Args:
        html: Documento HTML completo, com o CSS embutido.

    Returns:
        Os bytes do PDF.

    Raises:
        PDFDesignerError: Se o WeasyPrint não estiver disponível ou falhar.
    """
    try:
        from weasyprint import HTML  # import tardio: exige libs de sistema (GTK)
    except Exception as exc:  # noqa: BLE001 - ambiente sem as libs do WeasyPrint
        raise PDFDesignerError(
            "WeasyPrint indisponível neste ambiente (faltam bibliotecas de sistema)."
        ) from exc
    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:  # noqa: BLE001 - CSS inválido não pode derrubar a API
        raise PDFDesignerError(f"Falha ao renderizar o PDF: {exc}") from exc


async def gerar_html(
    client: AsyncAnthropic,
    *,
    titulo: str,
    conteudo: str,
    timbre: Timbre,
    referencias: list[dict[str, Any]] | None = None,
    instrucoes: str = "",
    modelo: str = MODELO_PADRAO,
) -> str:
    """Pede ao modelo o HTML da peça, já no sistema de design do escritório.

    Raises:
        PDFDesignerError: Se a resposta não for um documento HTML.
    """
    partes: list[dict[str, Any]] = list(referencias or [])
    if referencias:
        partes.append(
            {
                "type": "text",
                "text": (
                    "Os arquivos acima são REFERÊNCIA DE DESIGN enviados pelo usuário "
                    "e têm precedência sobre o sistema de design padrão: reproduza a "
                    "diagramação, a hierarquia tipográfica, as cores e a estrutura de "
                    "tabelas que você observa neles."
                ),
            }
        )
    partes.append(
        {"type": "text", "text": _montar_prompt(titulo, conteudo, timbre, instrucoes)}
    )

    resiliente = client.with_options(timeout=_TIMEOUT_S, max_retries=_TENTATIVAS)
    async with resiliente.messages.stream(
        model=modelo,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": partes}],
    ) as stream:
        bruto = "".join([texto async for texto in stream.text_stream])

    html = _limpar_html(bruto)
    if "<html" not in html.lower():
        raise PDFDesignerError("O modelo não devolveu um documento HTML.")
    return html


async def gerar_pdf_desenhado(
    client: AsyncAnthropic,
    *,
    titulo: str,
    conteudo: str,
    timbre: Timbre,
    referencias: list[dict[str, Any]] | None = None,
    instrucoes: str = "",
    modelo: str = MODELO_PADRAO,
) -> bytes:
    """Gera o PDF: o modelo escreve o HTML e o WeasyPrint renderiza.

    Args:
        client: Cliente Anthropic assíncrono da aplicação.
        titulo: Título da peça.
        conteudo: Corpo da peça em Markdown, como o agente produziu.
        timbre: Identidade visual do escritório logado.
        referencias: Blocos (imagem/documento) que o usuário anexou como
            referência de design, no formato da Messages API.
        instrucoes: Pedidos extras do usuário sobre o design.
        modelo: Modelo a usar.

    Returns:
        Os bytes do PDF pronto para download.

    Raises:
        PDFDesignerError: Se o modelo não devolver HTML ou a renderização falhar.
    """
    html = await gerar_html(
        client,
        titulo=titulo,
        conteudo=conteudo,
        timbre=timbre,
        referencias=referencias,
        instrucoes=instrucoes,
        modelo=modelo,
    )
    return renderizar_pdf(_aplicar_logo(html, timbre.logo))
