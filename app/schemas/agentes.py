"""Schemas da configuração de agentes (editável em runtime, sem redeploy)."""

from pydantic import BaseModel, ConfigDict, Field


class AgenteConfig(BaseModel):
    """Configuração completa de um agente (do banco ou do padrão do código)."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    nome: str
    descricao: str = ""
    icone: str = "scale"
    system_prompt: str
    modelo: str = "claude-sonnet-4-6"
    max_tokens: int = Field(default=1024, ge=256, le=8192)
    ativo: bool = True
    ordem: int = 0


class AgenteConfigUpdate(BaseModel):
    """Campos editáveis de um agente (todos opcionais — atualiza só o enviado)."""

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=240)
    icone: str | None = Field(default=None, max_length=40)
    system_prompt: str | None = Field(default=None, min_length=1)
    modelo: str | None = Field(default=None, max_length=60)
    max_tokens: int | None = Field(default=None, ge=256, le=8192)
    ativo: bool | None = None
    ordem: int | None = None
