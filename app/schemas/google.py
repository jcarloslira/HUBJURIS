"""Schemas da conexão do Google Drive por escritório (Composio multi-tenant)."""

from pydantic import BaseModel, Field


class PastaDrive(BaseModel):
    """Uma pasta do Drive do escritório (para escolher o acervo)."""

    id: str
    nome: str


class StatusDrive(BaseModel):
    """Estado da conexão do Drive do escritório logado."""

    configurado: bool
    conectado: bool
    acervo_definido: bool = False
    acervo_folder_id: str | None = None


class AcervoPayload(BaseModel):
    """Escolha da pasta-raiz do acervo de modelos do escritório."""

    folder_id: str = Field(min_length=1, max_length=200)


class ConectorStatus(BaseModel):
    """Estado de um conector do escritório (para a lista de Conectores)."""

    servico: str
    nome: str
    configurado: bool
    conectado: bool
