"""Schemas de exportação de documentos (Word/PDF/Excel)."""

from typing import Literal

from pydantic import BaseModel, Field


class ExportarPayload(BaseModel):
    """Pedido de exportação de um conteúdo (Markdown) para um formato."""

    conteudo: str = Field(min_length=1, max_length=200_000)
    formato: Literal["docx", "pdf", "xlsx"]
    titulo: str = Field(default="Documento", max_length=200)
    escritorio: str = Field(default="", max_length=160)
