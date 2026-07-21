"""Router de contas: cadastro, login, perfil, equipe e uso de tokens."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from supabase import AsyncClient

from app.config import Settings, get_settings
from app.dependencies import get_current_user, get_supabase
from app.schemas.auth import AuthUser
from app.schemas.contas import (
    LoginPayload,
    MembroCreate,
    MembroResponse,
    PerfilResponse,
    SessaoResponse,
    SignupPayload,
    UsoResumo,
)
from app.services.contas import ContaError, ContaService

router = APIRouter(prefix="/api", tags=["contas"])


def get_conta_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> ContaService:
    """Monta o service de contas com Supabase + http_client do lifespan."""
    http: httpx.AsyncClient = request.app.state.http_client
    return ContaService(supabase, http, settings)


_Svc = Annotated[ContaService, Depends(get_conta_service)]
_User = Annotated[AuthUser, Depends(get_current_user)]


def _erro(exc: ContaError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/auth/signup", response_model=SessaoResponse, status_code=201)
async def signup(payload: SignupPayload, svc: _Svc) -> SessaoResponse:
    """Cria a conta do escritório (usuário admin) e devolve a sessão."""
    try:
        return await svc.signup(payload)
    except ContaError as exc:
        raise _erro(exc) from exc


@router.post("/auth/login", response_model=SessaoResponse, status_code=200)
async def login(payload: LoginPayload, svc: _Svc) -> SessaoResponse:
    """Autentica e devolve token + perfil."""
    try:
        return await svc.login(payload)
    except ContaError as exc:
        raise _erro(exc) from exc


@router.get("/auth/me", response_model=PerfilResponse, status_code=200)
async def me(user: _User, svc: _Svc) -> PerfilResponse:
    """Perfil do usuário logado."""
    try:
        return await svc.perfil(user.id)
    except ContaError as exc:
        raise _erro(exc) from exc


@router.get("/auth/membros", response_model=list[MembroResponse], status_code=200)
async def listar_membros(user: _User, svc: _Svc) -> list[MembroResponse]:
    """Equipe do escritório do usuário logado."""
    try:
        perfil = await svc.perfil(user.id)
        return await svc.listar_membros(perfil.escritorio_id)
    except ContaError as exc:
        raise _erro(exc) from exc


@router.post("/auth/membros", response_model=MembroResponse, status_code=201)
async def criar_membro(payload: MembroCreate, user: _User, svc: _Svc) -> MembroResponse:
    """Admin cadastra um membro da equipe (advogado, estagiário...)."""
    try:
        perfil = await svc.perfil(user.id)
        if perfil.papel != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas administradores podem cadastrar membros",
            )
        return await svc.criar_membro(perfil.escritorio_id, payload)
    except ContaError as exc:
        raise _erro(exc) from exc


@router.get("/uso", response_model=UsoResumo, status_code=200)
async def uso(user: _User, svc: _Svc) -> UsoResumo:
    """Resumo de tokens consumidos pelo escritório."""
    try:
        perfil = await svc.perfil(user.id)
        return await svc.resumo_uso(perfil.escritorio_id)
    except ContaError as exc:
        raise _erro(exc) from exc
