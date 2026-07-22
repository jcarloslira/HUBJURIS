"""Dependências FastAPI do módulo de rifas."""

from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from supabase import AsyncClient

from app.config import Settings, get_settings
from app.dependencies import get_supabase
from app.services.mercadopago import MercadoPagoClient
from app.services.rifas import RifaService


def get_mercadopago(
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> MercadoPagoClient:
    """Retorna cliente do Mercado Pago usando o http_client do lifespan."""
    http: httpx.AsyncClient = request.app.state.http_client
    return MercadoPagoClient(settings, http)


def get_rifa_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
    mp: Annotated[MercadoPagoClient, Depends(get_mercadopago)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RifaService:
    """Retorna o service de rifas com Supabase + Pix já conectados."""
    return RifaService(supabase, mp, webhook_url=settings.MERCADO_PAGO_WEBHOOK_URL)


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Proteção simples por Bearer token para endpoints admin.

    Quando ADMIN_TOKEN não está configurado, libera acesso (modo dev).
    Em produção, defina ADMIN_TOKEN no .env.
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
