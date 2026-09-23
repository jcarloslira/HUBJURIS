"""Revisão de contrato em Word COM CONTROLE DE ALTERAÇÕES.

O escritório trabalha assim: manda o contrato do cliente, recebe de volta o mesmo
arquivo com o que foi cortado, reescrito e acrescentado **marcado**, para abrir no
Word, ler cada mudança e clicar em "Aceitar todas". Entregar um texto novo não
serve: perde a formatação do contrato e esconde o que mudou.

Um .docx é um zip com XML dentro. Alteração controlada é marcação nesse XML:

- inserção: ``<w:ins w:id w:author w:date>`` em volta do run;
- exclusão: ``<w:del …>`` em volta do run, e dentro dele o texto vira
  ``<w:delText>`` (não ``<w:t>``);
- parágrafo apagado inteiro: os runs em ``<w:del>`` **mais** a marca de fim de
  parágrafo apagada (``<w:pPr><w:rPr><w:del …/></w:rPr></w:pPr>``), senão o Word
  aceita a exclusão e deixa uma linha vazia no lugar.

Este módulo não decide o que mudar — quem decide é o modelo, que devolve uma lista
de alterações por parágrafo. Aqui só aplicamos, preservando todo o resto do
documento (estilos, cabeçalho, numeração, tabelas).
"""

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
_DOC = "word/document.xml"
# Brasília sem horário de verão: deslocamento fixo (a imagem slim não traz fusos).
_FUSO = timezone(timedelta(hours=-3))


class DocxRevisaoError(Exception):
    """Arquivo não é um .docx utilizável ou a revisão não pôde ser aplicada."""


@dataclass
class Alteracao:
    """Uma mudança pedida pelo modelo, já validada."""

    tipo: str  # substituir | remover | inserir
    indice: int  # parágrafo alvo (0-based, na ordem do documento)
    texto: str = ""


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _texto_do_paragrafo(paragrafo: etree._Element) -> str:
    """Texto visível do parágrafo (ignora o que já está marcado como excluído)."""
    partes: list[str] = []
    for no in paragrafo.iter():
        if no.tag == _q("t"):
            # Texto dentro de <w:del> já é exclusão de outra revisão.
            if not any(a.tag == _q("del") for a in no.iterancestors()):
                partes.append(no.text or "")
    return "".join(partes)


def paragrafos(documento: etree._Element) -> list[etree._Element]:
    """Todos os parágrafos na ordem do documento, inclusive dentro de tabelas."""
    corpo = documento.find(f".//{_q('body')}")
    if corpo is None:
        return []
    return [p for p in corpo.iter(_q("p"))]


def ler_paragrafos(docx: bytes) -> list[str]:
    """Texto de cada parágrafo do .docx, na ordem — a numeração que o modelo usa."""
    _, documento = _abrir(docx)
    return [_texto_do_paragrafo(p) for p in paragrafos(documento)]


def _abrir(docx: bytes) -> tuple[dict[str, bytes], etree._Element]:
    try:
        with zipfile.ZipFile(io.BytesIO(docx)) as zf:
            arquivos = {nome: zf.read(nome) for nome in zf.namelist()}
    except zipfile.BadZipFile as exc:
        raise DocxRevisaoError("O arquivo não é um .docx válido.") from exc
    if _DOC not in arquivos:
        raise DocxRevisaoError("O .docx não tem word/document.xml (arquivo corrompido?).")
    return arquivos, etree.fromstring(arquivos[_DOC])


def _rpr_modelo(paragrafo: etree._Element) -> etree._Element | None:
    """Formatação do primeiro run — o texto novo entra com a cara do parágrafo."""
    primeiro = paragrafo.find(f"{_q('r')}/{_q('rPr')}")
    return primeiro


class _Marcador:
    """Gera as marcas de revisão com id crescente, autor e data."""

    def __init__(self, autor: str, quando: datetime | None = None) -> None:
        self.autor = autor or "LexHub"
        self.data = (quando or datetime.now(_FUSO)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._id = 1000

    def _attrs(self) -> dict[str, str]:
        self._id += 1
        return {_q("id"): str(self._id), _q("author"): self.autor, _q("date"): self.data}

    def envelope(self, tag: str) -> etree._Element:
        """``<w:ins>`` ou ``<w:del>`` vazio, pronto para receber os runs."""
        return etree.Element(_q(tag), self._attrs())

    def run(self, texto: str, rpr: etree._Element | None, excluido: bool) -> etree._Element:
        run = etree.Element(_q("r"))
        if rpr is not None:
            run.append(_copia(rpr))
        alvo = etree.SubElement(run, _q("delText") if excluido else _q("t"))
        alvo.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        alvo.text = texto
        return run

    def marcar_fim_de_paragrafo(self, paragrafo: etree._Element) -> None:
        """Marca a quebra do parágrafo como excluída (funde com o de baixo).

        Sem isso, "aceitar todas" some com o texto mas deixa o parágrafo vazio —
        numa cláusula numerada, vira um item em branco no meio do contrato.
        """
        ppr = paragrafo.find(_q("pPr"))
        if ppr is None:
            ppr = etree.Element(_q("pPr"))
            paragrafo.insert(0, ppr)
        rpr = ppr.find(_q("rPr"))
        if rpr is None:
            rpr = etree.SubElement(ppr, _q("rPr"))
        # A ordem dentro de rPr é cobrada pelo schema: <w:del> vem primeiro.
        rpr.insert(0, etree.Element(_q("del"), self._attrs()))


def _copia(elemento: etree._Element) -> etree._Element:
    return etree.fromstring(etree.tostring(elemento))


def _palavras(texto: str) -> list[str]:
    """Quebra mantendo os espaços, para o diff não colar palavras."""
    return re.findall(r"\s+|[^\s]+", texto)


def _substituir(
    paragrafo: etree._Element, novo: str, marcador: _Marcador, antigo: str
) -> int:
    """Reescreve o parágrafo mostrando o que saiu e o que entrou. Devolve nº de trechos."""
    rpr = _rpr_modelo(paragrafo)
    ppr = paragrafo.find(_q("pPr"))
    for filho in list(paragrafo):
        if filho is not ppr:
            paragrafo.remove(filho)

    mudancas = 0
    comparador = SequenceMatcher(None, _palavras(antigo), _palavras(novo), autojunk=False)
    for acao, i1, i2, j1, j2 in comparador.get_opcodes():
        saiu = "".join(_palavras(antigo)[i1:i2])
        entrou = "".join(_palavras(novo)[j1:j2])
        if acao == "equal":
            paragrafo.append(marcador.run(saiu, rpr, excluido=False))
            continue
        if saiu:
            fora = marcador.envelope("del")
            fora.append(marcador.run(saiu, rpr, excluido=True))
            paragrafo.append(fora)
            mudancas += 1
        if entrou:
            dentro = marcador.envelope("ins")
            dentro.append(marcador.run(entrou, rpr, excluido=False))
            paragrafo.append(dentro)
            mudancas += 1
    return mudancas


def _remover(paragrafo: etree._Element, marcador: _Marcador) -> None:
    """Marca o parágrafo inteiro como excluído, inclusive a quebra de linha."""
    ppr = paragrafo.find(_q("pPr"))
    rpr = _rpr_modelo(paragrafo)
    texto = _texto_do_paragrafo(paragrafo)
    for filho in list(paragrafo):
        if filho is not ppr:
            paragrafo.remove(filho)
    if texto:
        fora = marcador.envelope("del")
        fora.append(marcador.run(texto, rpr, excluido=True))
        paragrafo.append(fora)
    marcador.marcar_fim_de_paragrafo(paragrafo)


def _inserir_depois(
    paragrafo: etree._Element, texto: str, marcador: _Marcador
) -> etree._Element:
    """Cria um parágrafo novo, inteiro marcado como inserido."""
    novo = etree.Element(_q("p"))
    ppr = paragrafo.find(_q("pPr"))
    if ppr is not None:
        novo.append(_copia(ppr))
    dentro = marcador.envelope("ins")
    dentro.append(marcador.run(texto, _rpr_modelo(paragrafo), excluido=False))
    novo.append(dentro)
    paragrafo.addnext(novo)
    return novo


def aplicar_revisao(
    docx: bytes, alteracoes: list[Alteracao], autor: str = "LexHub"
) -> tuple[bytes, int]:
    """Aplica as alterações no .docx original como revisões marcadas.

    Args:
        docx: Bytes do contrato original enviado pelo cliente.
        alteracoes: O que mudar, por índice de parágrafo (ordem do documento).
        autor: Nome que aparece em cada marca de revisão no Word.

    Returns:
        (bytes do .docx revisado, quantidade de alterações aplicadas).

    Raises:
        DocxRevisaoError: Arquivo inválido ou sem parágrafos.
    """
    arquivos, documento = _abrir(docx)
    lista = paragrafos(documento)
    if not lista:
        raise DocxRevisaoError("O documento não tem parágrafos para revisar.")

    marcador = _Marcador(autor)
    aplicadas = 0
    # De trás para frente: inserir ou remover não desloca os índices seguintes.
    for alteracao in sorted(alteracoes, key=lambda a: a.indice, reverse=True):
        if not 0 <= alteracao.indice < len(lista):
            continue
        alvo = lista[alteracao.indice]
        if alteracao.tipo == "remover":
            _remover(alvo, marcador)
            aplicadas += 1
        elif alteracao.tipo == "inserir" and alteracao.texto.strip():
            _inserir_depois(alvo, alteracao.texto.strip(), marcador)
            aplicadas += 1
        elif alteracao.tipo == "substituir" and alteracao.texto.strip():
            antigo = _texto_do_paragrafo(alvo)
            if antigo.strip() != alteracao.texto.strip():
                _substituir(alvo, alteracao.texto.strip(), marcador, antigo)
                aplicadas += 1

    arquivos[_DOC] = etree.tostring(
        documento, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in arquivos.items():
            zf.writestr(nome, conteudo)
    return saida.getvalue(), aplicadas


def alteracoes_do_modelo(dados: Any) -> list[Alteracao]:
    """Converte o JSON do modelo em alterações válidas, descartando o resto."""
    brutas = dados.get("alteracoes") if isinstance(dados, dict) else dados
    if not isinstance(brutas, list):
        return []
    validas: list[Alteracao] = []
    for item in brutas:
        if not isinstance(item, dict):
            continue
        tipo = str(item.get("tipo") or "").strip().lower()
        if tipo not in ("substituir", "remover", "inserir"):
            continue
        indice = item.get("indice", item.get("apos"))
        try:
            indice = int(indice)
        except (TypeError, ValueError):
            continue
        validas.append(
            Alteracao(tipo=tipo, indice=indice, texto=str(item.get("texto") or ""))
        )
    return validas
