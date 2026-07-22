"""Router admin da config de agentes — editar prompts/modelo sem redeploy.

Protegido por ADMIN_TOKEN (o mesmo do painel admin). É a config GLOBAL da
plataforma (vale para todos os escritórios), então fica com o dono da
plataforma, não com o admin de cada escritório.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import AsyncClient

from app.dependencies import get_supabase
from app.dependencies_condominios import require_admin
from app.schemas.agentes import AgenteConfig, AgenteConfigUpdate
from app.services.agentes_config import AgenteConfigError, AgenteConfigService
from app.services.chat import configs_padrao

router = APIRouter(
    prefix="/api/admin/agentes",
    tags=["admin-agentes"],
    dependencies=[Depends(require_admin)],
)


def get_config_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
) -> AgenteConfigService:
    """Service de config de agentes com o Supabase do lifespan."""
    return AgenteConfigService(supabase)


_Svc = Annotated[AgenteConfigService, Depends(get_config_service)]


@router.get("", response_model=list[AgenteConfig], status_code=200)
async def listar(svc: _Svc) -> list[AgenteConfig]:
    """Config atual de cada agente (do banco; padrões do código como fallback)."""
    return await svc.listar() or configs_padrao()


@router.put("/{slug}", response_model=AgenteConfig, status_code=200)
async def atualizar(slug: str, payload: AgenteConfigUpdate, svc: _Svc) -> AgenteConfig:
    """Edita as instruções/modelo de um agente. Vale na próxima resposta."""
    try:
        return await svc.atualizar(slug, payload)
    except AgenteConfigError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
