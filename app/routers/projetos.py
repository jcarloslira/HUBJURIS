"""Router de Projetos (condomínios) — multi-tenant, escopado pelo login.

Cada projeto é um condomínio com contexto e memória próprios, isolado por
escritório. Diferente do router `condominios` (Espinha, admin/single-tenant),
aqui o escritório vem SEMPRE do JWT do usuário logado.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient

from app.dependencies import get_current_user, get_supabase
from app.routers.contas import get_conta_service
from app.schemas.auth import AuthUser
from app.schemas.contas import PerfilResponse
from app.schemas.projetos import FatoCreate, FatoResponse, ProjetoCreate, ProjetoResponse
from app.services.contas import ContaError, ContaService
from app.services.projetos import ProjetoError, ProjetoService

router = APIRouter(prefix="/api", tags=["projetos"])


def get_projeto_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
) -> ProjetoService:
    """Service de projetos com o Supabase do lifespan."""
    return ProjetoService(supabase)


_Svc = Annotated[ProjetoService, Depends(get_projeto_service)]
_User = Annotated[AuthUser, Depends(get_current_user)]
_Contas = Annotated[ContaService, Depends(get_conta_service)]


async def _perfil(contas: ContaService, user: AuthUser) -> PerfilResponse:
    try:
        return await contas.perfil(user.id)
    except ContaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _erro(exc: ProjetoError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/projetos", response_model=list[ProjetoResponse], status_code=200)
async def listar_projetos(user: _User, contas: _Contas, svc: _Svc) -> list[ProjetoResponse]:
    """Lista os projetos/condomínios do escritório do usuário logado."""
    perfil = await _perfil(contas, user)
    return await svc.listar(perfil.escritorio_id)


@router.post("/projetos", response_model=ProjetoResponse, status_code=201)
async def criar_projeto(
    payload: ProjetoCreate, user: _User, contas: _Contas, svc: _Svc
) -> ProjetoResponse:
    """Cadastra um projeto/condomínio (idempotente por nome no escritório)."""
    perfil = await _perfil(contas, user)
    try:
        projeto, _ = await svc.criar(perfil.escritorio_id, payload)
    except ProjetoError as exc:
        raise _erro(exc) from exc
    return projeto


@router.get("/projetos/{projeto_id}/fatos", response_model=list[FatoResponse], status_code=200)
async def listar_fatos(
    projeto_id: str, user: _User, contas: _Contas, svc: _Svc
) -> list[FatoResponse]:
    """Lista os fatos memorizados sobre um projeto."""
    perfil = await _perfil(contas, user)
    try:
        return await svc.listar_fatos(perfil.escritorio_id, projeto_id)
    except ProjetoError as exc:
        raise _erro(exc) from exc


@router.post("/projetos/{projeto_id}/fatos", response_model=FatoResponse, status_code=201)
async def criar_fato(
    projeto_id: str, payload: FatoCreate, user: _User, contas: _Contas, svc: _Svc
) -> FatoResponse:
    """Adiciona manualmente um fato à memória de um projeto."""
    perfil = await _perfil(contas, user)
    try:
        return await svc.registrar_fato(
            perfil.escritorio_id, projeto_id, payload.fato, origem="manual"
        )
    except ProjetoError as exc:
        raise _erro(exc) from exc
