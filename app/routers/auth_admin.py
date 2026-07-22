"""Endpoint de autenticação do painel admin.

Aceita uma senha em texto puro e devolve um token Bearer válido
se bater com `ADMIN_TOKEN` do `.env`. Caso o Supabase não esteja
configurado, retorna 503.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import Settings
from app.config import get_settings as get_settings_dep

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    """Payload de login."""

    senha: str


class LoginResponse(BaseModel):
    """Resposta do login."""

    token: str
    expires_in: int = 86400  # 24h


@router.post("/admin", response_model=LoginResponse)
async def login_admin(
    payload: LoginPayload,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> LoginResponse:
    """Valida a senha do admin e devolve um token de sessão.

    Em produção (Supabase configurado): valida contra ADMIN_TOKEN.
    Sem Supabase configurado: retorna 503 explicitando o motivo.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase não configurado — autenticação requer backend em produção",
        )
    expected = settings.ADMIN_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_TOKEN não definido no .env",
        )
    if payload.senha != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha incorreta",
        )
    # Em produção ideal seria JWT assinado; aqui devolvemos o próprio token
    return LoginResponse(token=expected)
