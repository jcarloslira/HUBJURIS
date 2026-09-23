"""Planilhas Excel sob demanda — o que o escritório manda para a administradora.

Relatório em PDF é para o síndico ler. Planilha é para o escritório trabalhar:
conferir unidade a unidade com a lista da administradora, somar, filtrar, mandar
para o contador. Até aqui só existia o menu "Exportar", com as colunas que nós
escolhemos; o que o Dr. Wilker pediu foi poder dizer em português o que quer na
planilha e recebê-la pronta.

Duas decisões que separam isto de um CSV renomeado:

- **as somas são fórmulas** (``=SUM(D2:D31)``), não números congelados: mexeu numa
  linha, o total acompanha, que é como uma planilha tem de se comportar;
- **cada coluna tem tipo** — dinheiro sai como moeda (soma no Excel, alinha à
  direita), data como data, percentual como percentual. Texto "R$ 1.234,56" numa
  célula é um número perdido.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# Mesma paleta do PDF: a planilha é do mesmo escritório.
_PETROLEO = "2C5254"
_DOURADO = "A79E6E"
_LINHA_PAR = "F4F6F5"
_CINZA = "DFE3E1"

FORMATOS = {
    "texto": "@",
    "numero": "#,##0",
    "dinheiro": 'R$ #,##0.00',
    "data": "DD/MM/YYYY",
    "percentual": "0.0%",
}
TIPOS_SOMAVEIS = {"numero", "dinheiro"}

_LARGURA_MINIMA = 10
_LARGURA_MAXIMA = 62
_MAX_ABAS = 8
_MAX_LINHAS = 5_000
_MAX_COLUNAS = 30


class PlanilhaError(Exception):
    """Pedido de planilha que não dá para montar."""


@dataclass
class Coluna:
    """Uma coluna: o título que o usuário lê e o tipo que o Excel entende."""

    titulo: str
    tipo: str = "texto"

    def __post_init__(self) -> None:
        self.titulo = " ".join(str(self.titulo or "").split()) or "Coluna"
        self.tipo = self.tipo if self.tipo in FORMATOS else "texto"


@dataclass
class Aba:
    """Uma aba da planilha."""

    nome: str
    colunas: list[Coluna]
    linhas: list[list[Any]] = field(default_factory=list)
    somar: list[str] = field(default_factory=list)
    nota: str = ""

    def __post_init__(self) -> None:
        # O Excel recusa : \ / ? * [ ] no nome da aba e corta em 31 caracteres.
        limpo = re.sub(r"[:\\/?*\[\]]", " ", str(self.nome or "Dados"))
        self.nome = " ".join(limpo.split())[:31] or "Dados"


def _valor(bruto: Any, tipo: str) -> Any:
    """Converte o que o modelo escreveu para o que o Excel guarda de verdade."""
    if bruto is None or bruto == "":
        return None
    if tipo in ("numero", "dinheiro", "percentual"):
        if isinstance(bruto, (int, float)):
            return float(bruto) / 100 if tipo == "percentual" and abs(bruto) > 1 else float(bruto)
        texto = str(bruto).strip()
        negativo = texto.startswith("(") and texto.endswith(")")
        limpo = re.sub(r"[^\d,.\-]", "", texto).replace(".", "").replace(",", ".")
        # Sem vírgula decimal ("1.234.567") os pontos eram separador de milhar.
        if "," not in texto and limpo.count(".") == 1 and len(limpo.split(".")[-1]) == 3:
            limpo = limpo.replace(".", "")
        try:
            numero = float(limpo)
        except ValueError:
            return str(bruto)
        numero = -numero if negativo else numero
        return numero / 100 if tipo == "percentual" and abs(numero) > 1 else numero
    if tipo == "data":
        if isinstance(bruto, (date, datetime)):
            return bruto
        texto = str(bruto).strip()[:10]
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(texto, formato).date()
            except ValueError:
                continue
        return str(bruto)
    return str(bruto)


def _escrever_aba(planilha: Worksheet, aba: Aba) -> None:
    cabecalho = Font(bold=True, color="FFFFFF", size=10)
    fundo = PatternFill("solid", fgColor=_PETROLEO)
    zebra = PatternFill("solid", fgColor=_LINHA_PAR)
    borda = Border(bottom=Side(style="thin", color=_CINZA))

    for coluna, definicao in enumerate(aba.colunas, start=1):
        celula = planilha.cell(row=1, column=coluna, value=definicao.titulo)
        celula.font = cabecalho
        celula.fill = fundo
        celula.alignment = Alignment(vertical="center", wrap_text=True)
    planilha.row_dimensions[1].height = 26

    for indice, linha in enumerate(aba.linhas[:_MAX_LINHAS]):
        numero = indice + 2
        for coluna, definicao in enumerate(aba.colunas, start=1):
            bruto = linha[coluna - 1] if coluna - 1 < len(linha) else None
            celula = planilha.cell(row=numero, column=coluna, value=_valor(bruto, definicao.tipo))
            celula.number_format = FORMATOS[definicao.tipo]
            celula.border = borda
            celula.alignment = Alignment(
                vertical="top",
                horizontal="right" if definicao.tipo in TIPOS_SOMAVEIS else "left",
                wrap_text=definicao.tipo == "texto",
            )
            if indice % 2:
                celula.fill = zebra

    ultima = len(aba.linhas[:_MAX_LINHAS]) + 1
    _totalizar(planilha, aba, ultima)
    _dimensionar(planilha, aba)
    planilha.freeze_panes = "A2"
    if ultima > 1:
        planilha.auto_filter.ref = f"A1:{get_column_letter(len(aba.colunas))}{ultima}"


def _totalizar(planilha: Worksheet, aba: Aba, ultima: int) -> None:
    """Linha de total com fórmula viva — mexeu na tabela, o total acompanha."""
    somaveis = {t.lower() for t in aba.somar}
    alvos = [
        i
        for i, c in enumerate(aba.colunas, start=1)
        if c.tipo in TIPOS_SOMAVEIS and (not somaveis or c.titulo.lower() in somaveis)
    ]
    if not alvos or ultima < 2:
        return
    total = ultima + 1
    rotulo = planilha.cell(row=total, column=1, value="TOTAL")
    rotulo.font = Font(bold=True, color=_PETROLEO)
    for coluna in alvos:
        letra = get_column_letter(coluna)
        celula = planilha.cell(row=total, column=coluna, value=f"=SUM({letra}2:{letra}{ultima})")
        celula.number_format = FORMATOS[aba.colunas[coluna - 1].tipo]
        celula.font = Font(bold=True, color=_PETROLEO)
        celula.alignment = Alignment(horizontal="right")
    for coluna in range(1, len(aba.colunas) + 1):
        planilha.cell(row=total, column=coluna).border = Border(
            top=Side(style="medium", color=_DOURADO)
        )


def _dimensionar(planilha: Worksheet, aba: Aba) -> None:
    """Largura pelo conteúdo: coluna estreita esconde o dado, larga demais rola a tela."""
    for coluna, definicao in enumerate(aba.colunas, start=1):
        tamanhos = [len(definicao.titulo)]
        for linha in aba.linhas[:200]:
            if coluna - 1 < len(linha):
                tamanhos.append(len(str(linha[coluna - 1] or "")))
        largura = max(tamanhos) + 3
        planilha.column_dimensions[get_column_letter(coluna)].width = max(
            _LARGURA_MINIMA, min(_LARGURA_MAXIMA, largura)
        )


def montar_planilha(abas: list[Aba], *, autor: str = "") -> bytes:
    """Monta o .xlsx. Levanta PlanilhaError quando não há o que escrever."""
    reais = [a for a in abas if a.colunas][:_MAX_ABAS]
    if not reais:
        raise PlanilhaError("Nenhuma aba com colunas para montar.")
    livro = Workbook()
    livro.remove(livro.active)
    usados: set[str] = set()
    for aba in reais:
        nome = aba.nome
        sufixo = 2
        while nome.lower() in usados:  # duas abas com o mesmo nome quebram o arquivo
            nome = f"{aba.nome[:28]} {sufixo}"
            sufixo += 1
        usados.add(nome.lower())
        _escrever_aba(livro.create_sheet(title=nome), aba)
    if autor:
        livro.properties.creator = autor
    buffer = io.BytesIO()
    livro.save(buffer)
    return buffer.getvalue()


def abas_do_modelo(dados: Any) -> list[Aba]:
    """Traduz o JSON da ferramenta em abas, descartando em silêncio o que vier torto."""
    bruto = dados.get("abas") if isinstance(dados, dict) else dados
    if isinstance(bruto, dict):
        bruto = [bruto]
    if not isinstance(bruto, list):
        return []
    abas: list[Aba] = []
    for item in bruto[:_MAX_ABAS]:
        if not isinstance(item, dict):
            continue
        colunas = [
            Coluna(c.get("titulo", ""), str(c.get("tipo", "texto")).lower())
            if isinstance(c, dict)
            else Coluna(str(c))
            for c in (item.get("colunas") or [])[:_MAX_COLUNAS]
        ]
        if not colunas:
            continue
        linhas = [
            list(linha)[:_MAX_COLUNAS]
            for linha in (item.get("linhas") or [])
            if isinstance(linha, (list, tuple))
        ]
        somar = [str(s) for s in (item.get("somar") or []) if str(s).strip()]
        abas.append(
            Aba(
                nome=str(item.get("nome") or "Dados"),
                colunas=colunas,
                linhas=linhas,
                somar=somar,
                nota=str(item.get("nota") or ""),
            )
        )
    return abas
