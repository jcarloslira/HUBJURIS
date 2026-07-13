"""Dependências FastAPI do módulo condominial (Espinha)."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from supabase import AsyncClient

from app.config import Settings, get_settings
from app.dependencies import get_supabase
from app.services.condominios import CondominioService


def get_condominio_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
) -> CondominioService:
    """Retorna o service condominial com o Supabase do lifespan já conectado."""
    return CondominioService(supabase)


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Protege os endpoints do escritório por Bearer token (ADMIN_TOKEN).

    Sem ADMIN_TOKEN configurado, libera o acesso (modo dev local). Em produção,
    defina ADMIN_TOKEN no `.env`.
    """
    expected = settings.ADMIN_TOKEN
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de admin necessário",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )
