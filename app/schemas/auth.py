"""Schemas de autenticação."""

from pydantic import BaseModel, ConfigDict


class AuthUser(BaseModel):
    """Usuário autenticado via Supabase Auth.

    Apenas campos seguros para circular na aplicação — nunca expor tokens
    ou metadados internos do Supabase em responses.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None = None
