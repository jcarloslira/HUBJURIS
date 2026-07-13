"""Schemas do módulo condominial (escritório, condomínios, blocos, unidades)."""

from pydantic import BaseModel, ConfigDict, Field


class EscritorioUpsert(BaseModel):
    """Dados do escritório coletados no onboarding do Supervisor."""

    nome: str = Field(min_length=1)
    site: str | None = None
    instagram: str | None = None


class EscritorioResponse(BaseModel):
    """Escritório (tenant) já persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    site: str | None = None
    instagram: str | None = None
    google_conectado: bool = False


class CondominioCreate(BaseModel):
    """Cadastro de um condomínio (cliente do escritório)."""

    nome: str = Field(min_length=1)
    cnpj: str | None = None
    endereco: str | None = None


class CondominioResponse(BaseModel):
    """Condomínio persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    cnpj: str | None = None
    endereco: str | None = None
    status: str = "ativo"


class BlocoCreate(BaseModel):
    """Cadastro de um bloco de um condomínio."""

    nome: str = Field(min_length=1)


class BlocoResponse(BaseModel):
    """Bloco persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    condominio_id: str
    nome: str


class UnidadeCreate(BaseModel):
    """Cadastro de uma unidade de um bloco."""

    identificacao: str = Field(min_length=1)


class UnidadeResponse(BaseModel):
    """Unidade persistida."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    bloco_id: str
    identificacao: str
