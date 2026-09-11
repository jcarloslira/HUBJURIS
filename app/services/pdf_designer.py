"""Gerador de PDF "desenhado" — o modelo escreve o HTML, o WeasyPrint renderiza.

Os relatórios que o escritório já aprovou foram produzidos no claude.ai por
**WeasyPrint 69.0** (está gravado nos metadados dos PDFs): lá, o Claude escreve
HTML + CSS num contêiner e roda o WeasyPrint. É o mesmo motor que usamos aqui.

Dois modos:

- **molde** (padrão): a folha de estilo é fixa (``pdf_modelo``), medida nos PDFs
  aprovados. O modelo escreve só o HTML do conteúdo, com as classes do molde, e
  relatórios longos são escritos em PARTES PARALELAS — o tempo de uma peça passa
  a ser o da maior parte, não o da soma. Sem CSS para escrever, não há defeito de
  layout para revisar, então não há segunda passada.
- **livre**: o modelo escreve HTML + CSS do zero, seguindo anexos de referência
  (quando o usuário quer copiar outro visual). Mais lento; tem revisão visual.

A primeira versão delegava tudo à Agent Skill ``pdf`` da Anthropic, num sandbox:
20 minutos e ~R$ 4 por peça. Trazer a renderização para cá foi o primeiro corte.
"""

import asyncio
import base64
import math
import re
from typing import Any

from anthropic import AsyncAnthropic

from app.services import pdf_modelo
from app.services.design_system import ESPECIFICACAO
from app.services.documentos import Timbre

# Escrever o HTML/CSS da peça não exige o raciocínio do Opus.
MODELO_PADRAO = "claude-sonnet-5"
_MAX_TOKENS = 32_000
# A geração leva ~1 minuto; damos folga para peças longas sem prender o worker.
_TIMEOUT_S = 300.0
_TENTATIVAS = 2
# Quantas páginas voltam como imagem para o modelo conferir o próprio trabalho.
# Os defeitos de layout (cartão vazando, logo sumindo, texto cortado) aparecem
# nas primeiras; mandar o documento inteiro só encarece.
_PAGINAS_REVISAO = 3
_ESCALA_REVISAO = 1.4
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


_PROMPT_REVISAO = """As imagens acima são as primeiras páginas do PDF que o SEU
HTML produziu. Olhe cada uma como um revisor exigente e procure defeitos:

- texto ou cartão vazando da margem, cortado ou sobreposto
- coluna espremida a ponto de quebrar palavra de forma feia
- logotipo ilegível (colorido sobre fundo escuro) ou desproporcional
- cabeçalho/rodapé errado, "Pág. 0", numeração fora de lugar
- espaço vazio grande no meio da página, ou seção órfã no fim
- contraste insuficiente entre texto e fundo

Responda APENAS com regras CSS que corrijam o que você viu — sem <style>, sem
HTML, sem explicação, sem crases. As regras serão coladas no FIM da folha de
estilo, então elas vencem as anteriores; use seletores específicos o bastante
para acertar o alvo. Se o documento estiver correto, responda exatamente: NADA"""


def _paginas_png(pdf: bytes, limite: int = _PAGINAS_REVISAO) -> list[bytes]:
    """Rasteriza as primeiras páginas do PDF para o modelo poder olhá-las."""
    import io

    import pypdfium2

    documento = pypdfium2.PdfDocument(io.BytesIO(pdf))
    imagens: list[bytes] = []
    try:
        for indice in range(min(limite, len(documento))):
            imagem = documento[indice].render(scale=_ESCALA_REVISAO).to_pil()
            buffer = io.BytesIO()
            imagem.save(buffer, "PNG", optimize=True)
            imagens.append(buffer.getvalue())
    finally:
        documento.close()
    return imagens


async def revisar_html(
    client: AsyncAnthropic,
    *,
    html: str,
    paginas: list[bytes],
    modelo: str = MODELO_PADRAO,
) -> str:
    """Mostra ao modelo as páginas renderizadas e pede um REMENDO de CSS.

    Pedir o documento inteiro de volta custava outros ~8.000 tokens de saída e
    ~2,5 minutos — mais que a geração original. O remendo resolve os mesmos
    defeitos de layout em ~400 tokens, porque quase todo defeito visual é CSS.

    É o passo que faltava para igualar o claude.ai: renderizar, OLHAR o
    resultado e consertar. Como a renderização roda no nosso servidor, o
    custo extra é só o desta passada.

    Returns:
        O HTML corrigido; o original se a revisão não devolver documento válido.
    """
    partes: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(png).decode(),
            },
        }
        for png in paginas
    ]
    texto_revisao = f"""{_PROMPT_REVISAO}

HTML ATUAL:

{html}"""
    partes.append({"type": "text", "text": texto_revisao})

    resiliente = client.with_options(timeout=_TIMEOUT_S, max_retries=_TENTATIVAS)
    async with resiliente.messages.stream(
        model=modelo,
        max_tokens=2_000,
        messages=[{"role": "user", "content": partes}],
    ) as stream:
        bruto = "".join([texto async for texto in stream.text_stream])

    css = bruto.strip().strip("`").removeprefix("css").strip()
    if not css or css.upper().startswith("NADA") or "<" in css[:200]:
        return html
    # Injeta no fim da folha de estilo: o que vem por último vence na cascata.
    corte = html.lower().rfind("</style>")
    if corte == -1:
        return html
    remendo = f"""
/* revisão visual */
{css}
"""
    return html[:corte] + remendo + html[corte:]


# ─── Modo molde: folha de estilo fixa + partes em paralelo ─────────────────────

# Acima disto um relatório é dividido em partes escritas ao mesmo tempo. Medido
# num relatório de 9 páginas (16 mil caracteres): uma parte só, ~130 s; partes
# desequilibradas (a maior com 9 mil), 71 s; quatro partes de ~4 mil, 52 s.
_CHARS_POR_PARTE = 3_500
_PARTES_MAX = 6
_MAX_TOKENS_PARTE = 16_000

_SISTEMA_MOLDE = """Você é o designer de documentos de um escritório de advocacia \
brasileiro. Recebe um trecho de uma peça em Markdown e devolve o MESMO conteúdo \
diagramado em HTML, usando só os componentes do vocabulário abaixo. A folha de \
estilo já existe — foi medida nos relatórios que o sócio aprovou — e você não \
escreve CSS.

COMO PENSAR (é isto que faz o documento parecer obra de designer, e não texto exportado)
- Traduza informação em componente: número vira indicador, risco vira alerta, cada \
processo ou assunto relevante vira um cartão de caso com etiquetas, sequência vira \
linha do tempo, comparação vira tabela. Parágrafo só para análise que exige argumento.
- Hierarquia antes de volume: síndico, conselho ou sócio precisa saber em 10 segundos \
o que está bem, o que exige decisão e o que fazer. Título de cartão diz a conclusão \
("Apelação contra a Caixa parada na fila de julgamento — R$ 88.807,66"), não o \
assunto ("Processo 3").
- Negrito só no dado que decide a leitura (valor, prazo, resultado) — uma ou duas \
vezes por parágrafo.
- Cor com significado, nunca decoração: vermelho = risco/urgente, dourado = em \
curso/atenção, verde = favorável, azul/neutro = informativo.

FIDELIDADE
- Todo dado do trecho entra: números, processos, valores, datas, nomes, pendências. \
Não resuma, não invente, não arredonde (só o valor dentro do cartão de indicador \
vai abreviado).
- Campo que não veio na fonte: omita a linha — nunca escreva "não informado".
- Valores em R$ 1.234,56; datas dd/mm/aaaa; acentuação completa.

SAÍDA
Só o fragmento HTML do trecho (vai para dentro do <body>): sem <html>, <head>, \
<body>, <style>, atributo style, crases ou comentário antes ou depois."""

# Peças de texto corrido não se dividem: a argumentação depende da continuidade,
# e elas raramente passam de poucas páginas.
_MARCAS_PECA = (
    "excelentíssimo",
    "excelentissimo",
    "petição",
    "peticao",
    "notificação extrajudicial",
    "contrato de",
    "procuração",
    "termo de acordo",
    "ofício",
)


def _eh_peca(titulo: str, conteudo: str) -> bool:
    """Petição, notificação, contrato: texto corrido, sem capa de relatório."""
    alvo = f"{titulo}\n{conteudo[:1500]}".lower()
    return any(marca in alvo for marca in _MARCAS_PECA)


def _dividir_secoes(conteudo: str) -> list[str]:
    """Quebra o Markdown nas seções de nível mais alto (o título único não conta)."""
    linhas = conteudo.splitlines()
    niveis = [len(m.group(1)) for linha in linhas if (m := re.match(r"^(#{1,3})\s", linha))]
    if not niveis:
        return [conteudo]
    topo = min(niveis)
    if niveis.count(topo) <= 1 and any(n > topo for n in niveis):
        topo = min(n for n in niveis if n > topo)
    marca = re.compile(rf"^#{{{topo}}}\s")
    secoes: list[list[str]] = [[]]
    for linha in linhas:
        if marca.match(linha) and any(s.strip() for s in secoes[-1]):
            secoes.append([])
        secoes[-1].append(linha)
    return ["\n".join(s).strip() for s in secoes if "".join(s).strip()]


def _fatiar(secao: str, alvo: float) -> list[str]:
    """Quebra uma seção grande em pedaços menores que ``alvo``.

    O tempo da peça é o da MAIOR parte: uma seção com doze cartões de processo
    escrita inteira por uma parte só segura o documento todo. Corta primeiro
    nos subtítulos, depois nos parágrafos, por fim nas linhas.
    """
    if len(secao) <= alvo * 1.25:
        return [secao]
    for separador in (r"\n(?=#{1,6}\s)", r"\n\s*\n", r"\n"):
        pedacos = [p for p in re.split(separador, secao) if p.strip()]
        if len(pedacos) > 1:
            break
    else:
        return [secao]
    fatias: list[str] = [""]
    for pedaco in pedacos:
        if fatias[-1] and len(fatias[-1]) + len(pedaco) > alvo:
            fatias.append("")
        fatias[-1] = f"{fatias[-1]}\n\n{pedaco}" if fatias[-1] else pedaco
    return fatias


def _agrupar(secoes: list[str], partes: int) -> list[str]:
    """Junta seções em ``partes`` blocos de tamanho parecido, sem mudar a ordem."""
    if partes <= 1:
        return ["\n\n".join(secoes)]
    alvo = sum(len(s) for s in secoes) / partes
    unidades = [fatia for secao in secoes for fatia in _fatiar(secao, alvo)]
    blocos: list[list[str]] = [[]]
    acumulado = 0
    for unidade in unidades:
        restantes = partes - len(blocos)
        if blocos[-1] and acumulado + len(unidade) / 2 > alvo and restantes > 0:
            blocos.append([])
            acumulado = 0
        blocos[-1].append(unidade)
        acumulado += len(unidade)
    return ["\n\n".join(b) for b in blocos]


def dividir_em_partes(titulo: str, conteudo: str) -> list[str]:
    """Decide em quantas partes paralelas a peça é escrita."""
    if _eh_peca(titulo, conteudo) or len(conteudo) <= _CHARS_POR_PARTE:
        return [conteudo]
    partes = min(_PARTES_MAX, math.ceil(len(conteudo) / _CHARS_POR_PARTE))
    return _agrupar(_dividir_secoes(conteudo), partes)


def _estrutura(conteudo: str) -> str:
    """Os títulos da peça inteira — cada parte sabe onde está no todo."""
    titulos = [
        linha.strip("# ").strip()
        for linha in conteudo.splitlines()
        if re.match(r"^#{1,3}\s", linha)
    ]
    return "\n".join(f"- {t}" for t in titulos[:40])


def _identidade(timbre: Timbre) -> str:
    linhas = ["IDENTIDADE DO ESCRITÓRIO (use exatamente estes dados):"]
    linhas.append(f"- Nome: {timbre.nome or 'não informado'}")
    if timbre.subtitulo:
        linhas.append(f"- Área de atuação: {timbre.subtitulo}")
    if timbre.rodape:
        linhas.append(f"- Endereço/contato: {timbre.rodape}")
    return "\n".join(linhas)


def _pedido_da_parte(
    *,
    titulo: str,
    trecho: str,
    estrutura: str,
    indice: int,
    total: int,
    peca: bool,
    instrucoes: str,
) -> str:
    """Monta o pedido de UMA parte da peça."""
    partes = [f"TÍTULO DO DOCUMENTO: {titulo}"]
    if total > 1:
        partes.append(
            f"Este documento é escrito em {total} partes ao mesmo tempo; você escreve a "
            f"PARTE {indice + 1}. Estrutura completa, só para contexto:\n{estrutura}"
        )
    if indice == 0:
        if peca:
            partes.append(
                "É peça de texto corrido: sem capa de relatório. Envolva tudo em "
                '<div class="peca"> e mantenha o endereçamento e a estrutura da peça.'
            )
        else:
            partes.append(
                "Comece pela CAPA (componente capa) e siga com as seções do trecho."
            )
    else:
        partes.append(
            "Não escreva capa. Continue exatamente de onde a parte anterior parou, "
            "mantendo a numeração das seções do trecho."
        )
    if indice == total - 1 and not peca:
        partes.append(
            "Se o trecho terminar com conclusão, recomendações finais ou 'como ler', "
            "feche com o componente FECHO."
        )
    if instrucoes.strip():
        partes.append(f"PEDIDOS DO USUÁRIO:\n{instrucoes.strip()}")
    partes.append(f"TRECHO (Markdown):\n\n{trecho}")
    return "\n\n".join(partes)


def _limpar_corpo(bruto: str) -> str:
    """Deixa só o fragmento: sem cercas, sem CSS próprio, sem <html>/<body>."""
    texto = bruto.strip()
    texto = re.sub(r"^```(?:html)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    texto = re.sub(r"<style[\s\S]*?</style>", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<!doctype[^>]*>|</?(?:html|head|body)[^>]*>", "", texto, flags=re.I)
    texto = re.sub(r"<title>[\s\S]*?</title>|<meta[^>]*>", "", texto, flags=re.I)
    # O visual é da folha de estilo; estilo inline é o modelo improvisando.
    texto = re.sub(r'\sstyle="[^"]*"', "", texto)
    # Quebra forçada deixava meia página em branco (o relatório de agosto teve uma
    # página com um cartão só): a paginação fica por conta do break-inside do CSS.
    texto = re.sub(r'<div class="quebra">\s*</div>', "", texto)
    inicio = texto.find("<")
    return texto[inicio:].strip() if inicio > 0 else texto.strip()


async def _escrever_parte(
    client: AsyncAnthropic, *, sistema: str, pedido: str, modelo: str
) -> str:
    resiliente = client.with_options(timeout=_TIMEOUT_S, max_retries=_TENTATIVAS)
    async with resiliente.messages.stream(
        model=modelo,
        max_tokens=_MAX_TOKENS_PARTE,
        system=sistema,
        messages=[{"role": "user", "content": pedido}],
    ) as stream:
        bruto = "".join([texto async for texto in stream.text_stream])
    corpo = _limpar_corpo(bruto)
    if "<" not in corpo:
        raise PDFDesignerError("O modelo não devolveu o HTML de uma das partes.")
    return corpo


async def gerar_corpo_molde(
    client: AsyncAnthropic,
    *,
    titulo: str,
    conteudo: str,
    timbre: Timbre,
    instrucoes: str = "",
    modelo: str = MODELO_PADRAO,
) -> str:
    """Escreve o corpo da peça no molde, com as partes em paralelo."""
    peca = _eh_peca(titulo, conteudo)
    trechos = dividir_em_partes(titulo, conteudo)
    sistema = "\n\n".join(
        [_SISTEMA_MOLDE, pdf_modelo.guia(timbre), _identidade(timbre)]
    )
    estrutura = _estrutura(conteudo)
    tarefas = [
        _escrever_parte(
            client,
            sistema=sistema,
            pedido=_pedido_da_parte(
                titulo=titulo,
                trecho=trecho,
                estrutura=estrutura,
                indice=i,
                total=len(trechos),
                peca=peca,
                instrucoes=instrucoes,
            ),
            modelo=modelo,
        )
        for i, trecho in enumerate(trechos)
    ]
    corpos = await asyncio.gather(*tarefas)
    return "\n".join(corpos)


async def gerar_pdf_desenhado(
    client: AsyncAnthropic,
    *,
    titulo: str,
    conteudo: str,
    timbre: Timbre,
    referencias: list[dict[str, Any]] | None = None,
    instrucoes: str = "",
    modelo: str = MODELO_PADRAO,
    modo: str = "molde",
    revisar: bool = True,
) -> bytes:
    """Gera o PDF da peça.

    Args:
        client: Cliente Anthropic assíncrono da aplicação.
        titulo: Título da peça.
        conteudo: Corpo da peça em Markdown, como o agente produziu.
        timbre: Identidade visual do escritório logado.
        referencias: Blocos (imagem/documento) de referência de design — só
            usados no modo "livre".
        instrucoes: Pedidos extras do usuário sobre o design.
        modelo: Modelo a usar.
        modo: "molde" (folha de estilo do escritório, rápido) ou "livre" (o
            modelo desenha o CSS a partir das referências).
        revisar: No modo livre, mostra as páginas ao modelo e aplica a correção.

    Returns:
        Os bytes do PDF pronto para download.

    Raises:
        PDFDesignerError: Se o modelo não devolver HTML ou a renderização falhar.
    """
    if modo != "livre":
        corpo = await gerar_corpo_molde(
            client,
            titulo=titulo,
            conteudo=conteudo,
            timbre=timbre,
            instrucoes=instrucoes,
            modelo=modelo,
        )
        html = pdf_modelo.montar_documento(corpo, titulo=titulo, timbre=timbre)
        return renderizar_pdf(_aplicar_logo(html, timbre.logo))

    html = await gerar_html(
        client,
        titulo=titulo,
        conteudo=conteudo,
        timbre=timbre,
        referencias=referencias,
        instrucoes=instrucoes,
        modelo=modelo,
    )
    pdf = renderizar_pdf(_aplicar_logo(html, timbre.logo))
    if not revisar:
        return pdf

    # Renderiza, mostra ao modelo o que saiu e aplica a correção. Uma revisão que
    # falhe (imagem, rede, HTML inválido) não pode custar o documento inteiro:
    # nesse caso fica o PDF da primeira passada, que já é entregável.
    try:
        paginas = _paginas_png(pdf)
        if not paginas:
            return pdf
        corrigido = await revisar_html(client, html=html, paginas=paginas, modelo=modelo)
        if corrigido == html:
            return pdf
        return renderizar_pdf(_aplicar_logo(corrigido, timbre.logo))
    except Exception:  # noqa: BLE001 - revisão é melhoria, não pode derrubar a entrega
        return pdf
