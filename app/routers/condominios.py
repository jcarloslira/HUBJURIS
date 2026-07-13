"""Router da Espinha: escritório, condomínios, blocos e unidades (admin)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies_condominios import get_condominio_service, require_admin
from app.schemas.condominios import (
    BlocoCreate,
    BlocoResponse,
    CondominioCreate,
    CondominioResponse,
    EscritorioResponse,
    EscritorioUpsert,
    UnidadeCreate,
    UnidadeResponse,
)
from app.services.condominios import CondominioService

router = APIRouter(prefix="/api", tags=["condominios"], dependencies=[Depends(require_admin)])

_Svc = Annotated[CondominioService, Depends(get_condominio_service)]


@router.put("/escritorio", response_model=EscritorioResponse, status_code=200)
async def upsert_escritorio(payload: EscritorioUpsert, svc: _Svc) -> EscritorioResponse:
    """Cria ou atualiza o escritório com os dados coletados no onboarding."""
    return await svc.upsert_escritorio(payload)


@router.get("/escritorio", response_model=EscritorioResponse | None, status_code=200)
async def obter_escritorio(svc: _Svc) -> EscritorioResponse | None:
    """Retorna o escritório persistido, ou null se ainda não houve onboarding."""
    return await svc.obter_escritorio()


@router.post("/condominios", response_model=CondominioResponse, status_code=201)
async def criar_condominio(payload: CondominioCreate, svc: _Svc) -> CondominioResponse:
    """Cadastra um condomínio (cliente)."""
    return await svc.criar_condominio(payload)


@router.get("/condominios", response_model=list[CondominioResponse], status_code=200)
async def listar_condominios(svc: _Svc) -> list[CondominioResponse]:
    """Lista os condomínios cadastrados (alimenta o seletor de cliente)."""
    return await svc.listar_condominios()


@router.post(
    "/condominios/{condominio_id}/blocos",
    response_model=BlocoResponse,
    status_code=201,
)
async def criar_bloco(condominio_id: str, payload: BlocoCreate, svc: _Svc) -> BlocoResponse:
    """Cadastra um bloco de um condomínio."""
    return await svc.criar_bloco(condominio_id, payload)


@router.post("/blocos/{bloco_id}/unidades", response_model=UnidadeResponse, status_code=201)
async def criar_unidade(bloco_id: str, payload: UnidadeCreate, svc: _Svc) -> UnidadeResponse:
    """Cadastra uma unidade de um bloco."""
    return await svc.criar_unidade(bloco_id, payload)
