"""Schemas de Projetos (condomínios) — contexto isolado por escritório.

Um "Projeto" do hub é o próprio condomínio: cada um tem seu contexto, sua
memória de fatos aprendidos e suas conversas. Reaproveita a tabela
``condominios`` (multi-tenant, escopada por ``escritorio_id``).
"""

from pydantic import BaseModel, ConfigDict, Field


class ProjetoCreate(BaseModel):
    """Cadastro de um projeto/condomínio no escritório logado."""

    nome: str = Field(min_length=2, max_length=120)
    cnpj: str | None = Field(default=None, max_length=32)
    endereco: str | None = Field(default=None, max_length=240)


class ProjetoResponse(BaseModel):
    """Projeto/condomínio persistido, com contagem de fatos na memória."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    cnpj: str | None = None
    endereco: str | None = None
    status: str = "ativo"
    total_fatos: int = 0


class FatoCreate(BaseModel):
    """Fato aprendido sobre um projeto (memória curável)."""

    fato: str = Field(min_length=3, max_length=2000)


class FatoResponse(BaseModel):
    """Fato persistido na memória do projeto."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    fato: str
    origem: str = "agente"
