"""Schemas de contas: cadastro, login, equipe e uso de tokens."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Papel = str  # 'admin' | 'advogado' | 'estagiario' (validado no banco e no service)


class SignupPayload(BaseModel):
    """Cadastro inicial: cria o usuário admin e o escritório dele."""

    nome: str = Field(min_length=2)
    email: EmailStr
    senha: str = Field(min_length=8)
    nome_escritorio: str = Field(min_length=2)


class LoginPayload(BaseModel):
    """Login com e-mail e senha."""

    email: EmailStr
    senha: str = Field(min_length=1)


class PerfilResponse(BaseModel):
    """Perfil do usuário logado (sem dados sensíveis)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    nome: str
    email: str
    papel: str
    escritorio_id: str
    escritorio_nome: str


class SessaoResponse(BaseModel):
    """Sessão criada após signup/login."""

    access_token: str
    perfil: PerfilResponse


class MembroCreate(BaseModel):
    """Admin cadastra um membro da equipe (advogado, estagiário...)."""

    nome: str = Field(min_length=2)
    email: EmailStr
    senha: str = Field(min_length=8)
    papel: str = Field(pattern="^(admin|advogado|estagiario)$")


class MembroResponse(BaseModel):
    """Membro da equipe do escritório."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    nome: str
    email: str
    papel: str


class UsoModelo(BaseModel):
    """Total de tokens consumidos por modelo."""

    modelo: str
    tokens_entrada: int
    tokens_saida: int


class UsoResumo(BaseModel):
    """Resumo de uso do escritório (alimenta o painel Uso)."""

    total_entrada: int
    total_saida: int
    por_modelo: list[UsoModelo]
