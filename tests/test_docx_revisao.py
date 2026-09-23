"""Testes da revisão de contrato em Word com controle de alterações.

A prova que importa é a do Word: **aceitar todas** tem de dar o texto revisado e
**rejeitar todas** tem de devolver o contrato original, palavra por palavra.
"""

import io
import zipfile

import pytest
from docx import Document
from lxml import etree

from app.services.docx_revisao import (
    Alteracao,
    DocxRevisaoError,
    alteracoes_do_modelo,
    aplicar_revisao,
    ler_paragrafos,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

CLAUSULAS = [
    "CLÁUSULA 1. O prazo de vigência é de 12 (doze) meses.",
    "CLÁUSULA 2. A multa por rescisão antecipada é de 50% do valor total do contrato.",
    "CLÁUSULA 3. Fica eleito o foro da comarca de São Paulo.",
]


def _contrato(paragrafos: list[str] | None = None) -> bytes:
    doc = Document()
    for texto in paragrafos or CLAUSULAS:
        doc.add_paragraph(texto)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _resolver(docx: bytes, aceitar: bool) -> list[str]:
    """Faz o que o Word faz em 'Aceitar todas' / 'Rejeitar todas'."""
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        raiz = etree.fromstring(zf.read("word/document.xml"))
    # As marcas somem no processamento: anote antes o que cada parágrafo era.
    fundir_com_o_proximo = {
        paragrafo
        for paragrafo in raiz.iter(f"{W}p")
        if paragrafo.find(f"{W}pPr/{W}rPr/{W}del") is not None
    }
    # Parágrafo que só existe por causa da revisão: ao rejeitar, desaparece.
    nasceu_da_revisao = {
        paragrafo
        for paragrafo in raiz.iter(f"{W}p")
        if paragrafo.find(f"{W}ins") is not None and paragrafo.find(f"{W}r") is None
    }
    for insercao in raiz.findall(f".//{W}ins"):
        pai = insercao.getparent()
        if aceitar:
            for filho in list(insercao):
                pai.insert(list(pai).index(insercao), filho)
        pai.remove(insercao)
    for exclusao in raiz.findall(f".//{W}del"):
        pai = exclusao.getparent()
        if pai.tag != f"{W}p":  # a marca do fim de parágrafo, tratada acima
            pai.remove(exclusao)
            continue
        if not aceitar:
            for filho in list(exclusao):
                for texto in filho.findall(f"{W}delText"):
                    texto.tag = f"{W}t"
                pai.insert(list(pai).index(exclusao), filho)
        pai.remove(exclusao)
    paragrafos = []
    for paragrafo in raiz.iter(f"{W}p"):
        texto = "".join(t.text or "" for t in paragrafo.iter(f"{W}t"))
        # Quebra apagada e sem texto: ao aceitar, o Word funde com o de baixo.
        if aceitar and paragrafo in fundir_com_o_proximo and not texto.strip():
            continue
        if not aceitar and paragrafo in nasceu_da_revisao:
            continue
        paragrafos.append(texto)
    return paragrafos


def test_le_os_paragrafos_na_ordem_do_documento() -> None:
    assert ler_paragrafos(_contrato()) == CLAUSULAS


def test_aceitar_todas_entrega_o_contrato_revisado() -> None:
    revisado, aplicadas = aplicar_revisao(
        _contrato(),
        [
            Alteracao("substituir", 1, "CLÁUSULA 2. A multa por rescisão antecipada é de 10%"
                      " do valor total do contrato."),
            Alteracao("remover", 2),
            Alteracao("inserir", 2, "CLÁUSULA 3. Fica eleito o foro de Brasília/DF."),
        ],
        autor="Jales Advogados",
    )

    assert aplicadas == 3
    assert _resolver(revisado, aceitar=True) == [
        CLAUSULAS[0],
        "CLÁUSULA 2. A multa por rescisão antecipada é de 10% do valor total do contrato.",
        "CLÁUSULA 3. Fica eleito o foro de Brasília/DF.",
    ]


def test_rejeitar_todas_devolve_o_contrato_do_cliente_intacto() -> None:
    """O advogado tem de poder descartar a revisão inteira sem perder o original."""
    revisado, _ = aplicar_revisao(
        _contrato(),
        [
            Alteracao("substituir", 1, "CLÁUSULA 2. Não há multa."),
            Alteracao("remover", 2),
            Alteracao("inserir", 0, "CLÁUSULA NOVA. Seguro obrigatório."),
        ],
    )

    assert _resolver(revisado, aceitar=False) == CLAUSULAS


def test_marca_traz_autor_e_data_para_o_word_mostrar() -> None:
    revisado, _ = aplicar_revisao(
        _contrato(), [Alteracao("substituir", 0, "CLÁUSULA 1. O prazo é de 24 meses.")],
        autor="Jales Advogados",
    )
    with zipfile.ZipFile(io.BytesIO(revisado)) as zf:
        raiz = etree.fromstring(zf.read("word/document.xml"))

    marcas = [e for e in raiz.iter() if e.tag in (f"{W}ins", f"{W}del")]
    assert marcas, "sem marcação, o Word abre como texto comum"
    assert all(m.get(f"{W}author") == "Jales Advogados" for m in marcas)
    assert all(m.get(f"{W}date") for m in marcas)
    # Texto excluído usa <w:delText>; com <w:t> o Word mostra a exclusão como texto normal.
    assert raiz.find(f".//{W}del/{W}r/{W}delText") is not None


def test_so_o_trecho_alterado_vira_marca() -> None:
    """Reescrever o parágrafo inteiro encheria o contrato de marcas falsas."""
    revisado, _ = aplicar_revisao(
        _contrato(),
        [Alteracao("substituir", 1, CLAUSULAS[1].replace("50%", "10%"))],
    )
    with zipfile.ZipFile(io.BytesIO(revisado)) as zf:
        raiz = etree.fromstring(zf.read("word/document.xml"))

    excluido = "".join(t.text or "" for t in raiz.iter(f"{W}delText"))
    inserido = "".join(
        t.text or "" for ins in raiz.iter(f"{W}ins") for t in ins.iter(f"{W}t")
    )
    assert "50%" in excluido and "10%" in inserido
    assert "multa" not in excluido.lower()  # o resto da cláusula não foi tocado


def test_paragrafo_removido_nao_deixa_linha_vazia_no_lugar() -> None:
    """Sem apagar a marca de fim de parágrafo, sobra um item em branco na numeração."""
    revisado, _ = aplicar_revisao(_contrato(), [Alteracao("remover", 1)])
    with zipfile.ZipFile(io.BytesIO(revisado)) as zf:
        raiz = etree.fromstring(zf.read("word/document.xml"))

    assert raiz.find(f".//{W}p/{W}pPr/{W}rPr/{W}del") is not None
    assert len(_resolver(revisado, aceitar=True)) == 2


def test_indice_fora_do_documento_e_ignorado() -> None:
    revisado, aplicadas = aplicar_revisao(
        _contrato(), [Alteracao("substituir", 99, "texto qualquer")]
    )

    assert aplicadas == 0
    assert ler_paragrafos(revisado) == CLAUSULAS


def test_alteracao_que_nao_muda_nada_nao_vira_marca() -> None:
    _, aplicadas = aplicar_revisao(_contrato(), [Alteracao("substituir", 0, CLAUSULAS[0])])

    assert aplicadas == 0


def test_varias_alteracoes_nao_embaralham_os_indices() -> None:
    """Inserir no meio desloca o resto: por isso aplicamos de trás para frente."""
    revisado, aplicadas = aplicar_revisao(
        _contrato(),
        [
            Alteracao("inserir", 0, "PARÁGRAFO NOVO A"),
            Alteracao("substituir", 2, "CLÁUSULA 3. Fica eleito o foro de Brasília/DF."),
        ],
    )

    assert aplicadas == 2
    aceito = _resolver(revisado, aceitar=True)
    assert aceito[1] == "PARÁGRAFO NOVO A"
    assert aceito[-1] == "CLÁUSULA 3. Fica eleito o foro de Brasília/DF."


def test_arquivo_que_nao_e_docx_vira_erro_de_dominio() -> None:
    with pytest.raises(DocxRevisaoError):
        aplicar_revisao(b"isto nao e um docx", [Alteracao("remover", 0)])


def test_json_do_modelo_vira_alteracoes_validas() -> None:
    alteracoes = alteracoes_do_modelo(
        {
            "resumo": "riscos encontrados",
            "alteracoes": [
                {"tipo": "substituir", "indice": 2, "texto": "novo texto"},
                {"tipo": "inserir", "apos": 5, "texto": "cláusula nova"},
                {"tipo": "remover", "indice": "7"},
                {"tipo": "inventado", "indice": 1},  # tipo desconhecido
                {"tipo": "substituir", "indice": "x"},  # índice inválido
                "lixo",
            ],
        }
    )

    assert [(a.tipo, a.indice) for a in alteracoes] == [
        ("substituir", 2),
        ("inserir", 5),
        ("remover", 7),
    ]
