"""Testes do gerador de PDF desenhado (partes puras, sem chamar a API)."""

import re

import pytest

from app.services.design_system import ESPECIFICACAO, PALETA, SEMANTICA
from app.services.documentos import Timbre
from app.services.pdf_designer import (
    PDFDesignerError,
    _aplicar_logo,
    _limpar_html,
    _mime_da_imagem,
    _montar_prompt,
    renderizar_pdf,
)

_PNG = b"\x89PNG\r\n\x1a\n"


def test_limpa_cerca_de_markdown() -> None:
    """O modelo às vezes embrulha a resposta em crases; isso quebraria o render."""
    bruto = "```html\n<!doctype html><html><body>x</body></html>\n```"

    assert _limpar_html(bruto).startswith("<!doctype html>")
    assert "```" not in _limpar_html(bruto)


def test_limpa_preambulo_antes_do_doctype() -> None:
    bruto = "Claro! Segue o documento:\n\n<!doctype html><html></html>"

    assert _limpar_html(bruto).startswith("<!doctype html>")


def test_html_limpo_passa_intacto() -> None:
    puro = "<!doctype html><html><body>ok</body></html>"

    assert _limpar_html(puro) == puro


def test_mime_por_bytes_magicos() -> None:
    assert _mime_da_imagem(_PNG) == "image/png"
    assert _mime_da_imagem(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert _mime_da_imagem(b"qualquer") == "application/octet-stream"


def test_logo_vira_data_uri() -> None:
    html = _aplicar_logo('<img src="__LOGO_DO_ESCRITORIO__" alt="">', _PNG)

    assert "data:image/png;base64," in html
    assert "__LOGO_DO_ESCRITORIO__" not in html


def test_sem_logo_a_tag_some_em_vez_de_quebrar() -> None:
    """Marcador não substituído viraria uma imagem quebrada no PDF entregue."""
    html = _aplicar_logo('<p>a</p><img src="__LOGO_DO_ESCRITORIO__" alt=""><p>b</p>', None)

    assert "__LOGO" not in html
    assert "<p>a</p><p>b</p>" == html


def test_prompt_carrega_sistema_de_design_e_identidade() -> None:
    prompt = _montar_prompt(
        "Relatório",
        "## 1. Panorama",
        Timbre(nome="Jales & Jales", cor="#1A3A3B", subtitulo="Condominial"),
        instrucoes="Destinatário: Síndica.",
    )

    assert PALETA["dourado"] in prompt  # sistema de design embutido
    assert "Jales & Jales" in prompt
    assert "#1A3A3B" in prompt
    assert "Destinatário: Síndica." in prompt
    assert "## 1. Panorama" in prompt


def test_prompt_so_promete_logo_quando_existe() -> None:
    sem = _montar_prompt("t", "c", Timbre(nome="X"), "")
    com = _montar_prompt("t", "c", Timbre(nome="X", logo=_PNG), "")

    assert "__LOGO_DO_ESCRITORIO__" not in sem
    assert "__LOGO_DO_ESCRITORIO__" in com


def test_render_falha_vira_erro_de_dominio() -> None:
    """Sem as libs do WeasyPrint (ou com CSS inválido) a API não pode dar 500 cru."""
    with pytest.raises(PDFDesignerError):
        renderizar_pdf("<html><body>" + "\x00" * 10 + "</body></html>")


def test_especificacao_carrega_a_paleta_aprovada() -> None:
    """A spec é o que garante o visual; se perder a paleta, perde tudo."""
    for cor in PALETA.values():
        assert cor in ESPECIFICACAO
    for cor in SEMANTICA.values():
        assert cor in ESPECIFICACAO
    # Os componentes que separam um painel de um texto corrido.
    for componente in (
        "CARTÃO DE INDICADOR",
        "CARTÕES DE PRIORIDADE",
        "LINHA DO TEMPO",
        "LISTA DE MOVIMENTAÇÕES",
        "FAIXA DE ALERTA",
    ):
        assert componente in ESPECIFICACAO


def test_rasteriza_so_as_primeiras_paginas() -> None:
    """Mandar o documento inteiro como imagem encarece sem achar mais defeito."""
    import io

    import pypdfium2

    from app.services.pdf_designer import _PAGINAS_REVISAO, _paginas_png, renderizar_pdf

    corpo = "<p>x</p><div style='page-break-after:always'></div>" * 6
    try:
        pdf = renderizar_pdf(f"<html><body>{corpo}</body></html>")
    except Exception:  # noqa: BLE001 - só roda onde as libs do WeasyPrint existem
        pytest.skip("sem as bibliotecas de sistema do WeasyPrint")

    assert len(pypdfium2.PdfDocument(io.BytesIO(pdf))) > _PAGINAS_REVISAO
    assert len(_paginas_png(pdf)) == _PAGINAS_REVISAO


async def test_revisao_ignora_resposta_que_nao_e_html() -> None:
    """Uma revisão malsucedida não pode trocar a peça por lixo."""
    from unittest.mock import MagicMock

    from app.services.pdf_designer import revisar_html

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield "desculpe, nao consegui revisar"

            return gen()

    client = MagicMock()
    client.with_options.return_value.messages.stream = MagicMock(return_value=_Stream())
    original = "<html><body>peça boa</body></html>"

    assert await revisar_html(client, html=original, paginas=[b"\x89PNG"]) == original


async def test_revisao_injeta_css_no_fim_da_folha_de_estilo() -> None:
    """O remendo tem de entrar por último para vencer na cascata."""
    from unittest.mock import MagicMock

    from app.services.pdf_designer import revisar_html

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield ".cartao { max-width: 100%; }"

            return gen()

    client = MagicMock()
    client.with_options.return_value.messages.stream = MagicMock(return_value=_Stream())
    html = "<html><head><style>.cartao{width:900px}</style></head><body>x</body></html>"

    saida = await revisar_html(client, html=html, paginas=[b"\x89PNG"])

    assert ".cartao { max-width: 100%; }" in saida
    assert saida.index("max-width") < saida.index("</style>")  # dentro do <style>
    assert saida.index("width:900px") < saida.index("max-width")  # e depois da regra original


async def test_revisao_sem_defeito_devolve_o_html_intacto() -> None:
    """Responder NADA não pode sujar o documento com CSS vazio."""
    from unittest.mock import MagicMock

    from app.services.pdf_designer import revisar_html

    class _Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        @property
        def text_stream(self):
            async def gen():
                yield "NADA"

            return gen()

    client = MagicMock()
    client.with_options.return_value.messages.stream = MagicMock(return_value=_Stream())
    html = "<html><head><style>a{}</style></head><body>ok</body></html>"

    assert await revisar_html(client, html=html, paginas=[b"\x89PNG"]) == html


# ─── Modo molde ──────────────────────────────────────────────────────────────


def test_relatorio_longo_vira_partes_equilibradas_sem_perder_texto() -> None:
    """O tempo da peça é o da MAIOR parte; uma seção gorda não pode segurar tudo."""
    from app.services.pdf_designer import _CHARS_POR_PARTE, dividir_em_partes

    cartoes = "\n\n".join(f"### Unidade {i}\n" + "texto do caso " * 60 for i in range(12))
    md = "## 1. Panorama\nresumo curto\n\n## 2. Cobranças\n" + cartoes + "\n\n## 3. Fecho\nfim"

    partes = dividir_em_partes("Relatório", md)

    assert len(partes) > 1
    assert max(len(p) for p in partes) < _CHARS_POR_PARTE * 1.6
    junto = "\n".join(partes)
    for i in range(12):
        assert f"### Unidade {i}" in junto
    assert junto.index("## 1. Panorama") < junto.index("### Unidade 11") < junto.index("## 3.")


def test_peca_de_texto_corrido_nao_se_divide() -> None:
    """A argumentação de uma petição depende da continuidade."""
    from app.services.pdf_designer import dividir_em_partes

    md = "EXCELENTÍSSIMO SENHOR DOUTOR JUIZ\n\n" + "## Dos fatos\n" + "argumento " * 2000

    assert len(dividir_em_partes("Petição inicial", md)) == 1


def test_documento_curto_vai_numa_parte_so() -> None:
    from app.services.pdf_designer import dividir_em_partes

    assert dividir_em_partes("Relatório", "## 1. Panorama\ncurto") == ["## 1. Panorama\ncurto"]


def test_corpo_do_molde_perde_css_e_estilo_inline() -> None:
    """O visual é da folha de estilo; CSS do modelo é improviso que quebra o molde."""
    from app.services.pdf_designer import _limpar_corpo

    bruto = (
        "```html\n<!doctype html><html><head><style>h2{color:red}</style></head>"
        '<body><h2 style="color:red">1. Panorama</h2><div class="kpis"></div></body></html>\n```'
    )

    corpo = _limpar_corpo(bruto)

    assert corpo.startswith("<h2>1. Panorama</h2>")
    assert "quebra" not in _limpar_corpo('<p>a</p><div class="quebra"></div><h2>b</h2>')
    assert "style" not in corpo
    assert "<body" not in corpo and "<html" not in corpo


def test_molde_tem_capa_sem_numero_e_rodape_com_total_de_paginas() -> None:
    from app.services.pdf_modelo import montar_documento

    html = montar_documento("<h2>x</h2>", titulo="T", timbre=Timbre(nome="Jales & Jales"))

    assert "@page capa" in html
    assert 'counter(page) " / " counter(pages)' in html
    assert "Jales & Jales · Documento confidencial" in html


def test_cor_da_marca_so_troca_o_petroleo_se_for_escura() -> None:
    """Dourado do logo ou o marrom padrão deixariam a faixa clara demais."""
    from app.services.pdf_modelo import PETROLEO, _cor_primaria

    assert _cor_primaria("#9A6A3A") == PETROLEO  # cor padrão de quem nunca escolheu
    assert _cor_primaria("#A79E6E") == PETROLEO  # dourado: claro demais
    assert _cor_primaria("#0B2545") == "#0B2545"  # azul-marinho: vale
    assert _cor_primaria("") == PETROLEO


def test_guia_so_poe_logo_na_capa_quando_existe() -> None:
    from app.services.pdf_modelo import MARCADOR_LOGO, guia

    assert MARCADOR_LOGO not in guia(Timbre(nome="X"))
    assert MARCADOR_LOGO in guia(Timbre(nome="X", logo=_PNG))


@pytest.mark.asyncio
async def test_partes_sao_escritas_em_paralelo_e_montadas_em_ordem() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.services import pdf_designer

    vistos: list[str] = []

    class _Stream:
        def __init__(self, pedido: str) -> None:
            self.pedido = pedido

        async def __aenter__(self) -> "_Stream":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        @property
        async def text_stream(self):  # type: ignore[no-untyped-def]
            await asyncio.sleep(0)
            parte = self.pedido.split("PARTE ")[1][0] if "PARTE " in self.pedido else "1"
            yield f"<section>parte {parte}</section>"

    class _Mensagens:
        def stream(self, **kw: object) -> _Stream:
            pedido = kw["messages"][0]["content"]  # type: ignore[index]
            vistos.append(pedido)  # type: ignore[arg-type]
            return _Stream(pedido)  # type: ignore[arg-type]

    client = SimpleNamespace(
        with_options=lambda **_: SimpleNamespace(messages=_Mensagens()),
    )
    md = "\n\n".join(f"## {i}. Seção\n" + "conteúdo " * 500 for i in range(1, 5))

    corpo = await pdf_designer.gerar_corpo_molde(
        client,  # type: ignore[arg-type]
        titulo="Relatório",
        conteudo=md,
        timbre=Timbre(nome="X"),
    )

    assert len(vistos) > 1
    assert "CAPA" in vistos[0] and "Não escreva capa" in vistos[1]
    ordem = [int(n) for n in re.findall(r"parte (\d)", corpo)]
    assert ordem == sorted(ordem)
