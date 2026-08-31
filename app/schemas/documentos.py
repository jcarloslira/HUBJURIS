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
    """Pedido de PDF "desenhado" — o agente escreve o código do documento.

    Diferente de :class:`ExportarPayload` (molde fixo), aqui o modelo projeta o
    layout. Aceita anexos de referência para reproduzir um design existente.
    """

    conteudo: str = Field(min_length=1, max_length=200_000)
    titulo: str = Field(default="Documento", max_length=200)
    instrucoes: str = Field(default="", max_length=4_000)
    referencias: list[AnexoIn] = Field(default_factory=list, max_length=4)
