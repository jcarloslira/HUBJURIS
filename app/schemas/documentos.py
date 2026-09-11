"""Schemas de exportação de documentos (Word/PDF/Excel)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.chat import AnexoIn


class ExportarPayload(BaseModel):
    """Pedido de exportação de um conteúdo (Markdown) para um formato."""

    conteudo: str = Field(min_length=1, max_length=200_000)
    formato: Literal["docx", "pdf", "xlsx"]
    titulo: str = Field(default="Documento", max_length=200)
    escritorio: str = Field(default="", max_length=160)


class PdfDesenhadoPayload(BaseModel):
    """Pedido de PDF "desenhado" — o modelo diagrama a peça e o WeasyPrint renderiza.

    ``modo="molde"`` usa a folha de estilo do escritório (a dos relatórios
    aprovados) e é o rápido; ``modo="livre"`` deixa o modelo desenhar o CSS a
    partir dos anexos de referência, para copiar outro visual.
    """

    conteudo: str = Field(min_length=1, max_length=200_000)
    titulo: str = Field(default="Documento", max_length=200)
    instrucoes: str = Field(default="", max_length=4_000)
    referencias: list[AnexoIn] = Field(default_factory=list, max_length=4)
    modo: Literal["molde", "livre"] = "molde"
