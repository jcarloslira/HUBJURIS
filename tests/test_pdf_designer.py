"""Testes do gerador de PDF desenhado (partes puras, sem chamar a API)."""

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
