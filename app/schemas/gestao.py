"""Schemas da gestão condominial (cadastro e anotações do diário)."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class CondominioUpdate(BaseModel):
    """Campos de gestão editáveis de um condomínio (envie só o que muda)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=2, max_length=200)
    cnpj: str | None = Field(default=None, max_length=30)
    endereco: str | None = Field(default=None, max_length=300)
    cidade: str | None = Field(default=None, max_length=100)
    uf: str | None = Field(default=None, max_length=2)
    sindico: str | None = Field(default=None, max_length=200)
    administradora: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=30)
    observacoes: str | None = Field(default=None, max_length=4_000)
    easyjur_cliente_id: str | None = Field(default=None, max_length=30)
    tiflux_cliente_id: str | None = Field(default=None, max_length=30)


class AnotacaoCreate(BaseModel):
    """Anotação do escritório no diário (reunião, assembleia, ligação...)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    titulo: str = Field(min_length=3, max_length=300)
    descricao: str = Field(default="", max_length=4_000)
    dia: date | None = None
