"""Rotas públicas do módulo de rifas: catálogo, números e checkout."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies_rifas import get_rifa_service, require_admin
from app.schemas.rifas import (
    NumerosResponse,
    PedidoCreate,
    PedidoResponse,
    RifaCreate,
    RifaResponse,
    RifaUpdate,
    SorteioRequest,
    SorteioResponse,
)
from app.services.rifas import (
    NumeroIndisponivel,
    OperacaoInvalida,
    RifaNaoEncontrada,
    RifaService,
    SorteioInvalido,
)

router = APIRouter(prefix="/api/rifas", tags=["rifas"])


# ── Público ───────────────────────────────────────────────────


@router.get("", response_model=list[RifaResponse])
async def listar_rifas(
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> list[RifaResponse]:
    """Catálogo público de rifas ativas, encerradas e sorteadas."""
    return await svc.listar_ativas()


@router.get("/{rifa_id}", response_model=RifaResponse)
async def obter_rifa(
    rifa_id: str,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> RifaResponse:
    """Detalhes de uma rifa."""
    try:
        return await svc.obter(rifa_id)
    except RifaNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{rifa_id}/numeros", response_model=NumerosResponse)
async def listar_numeros(
    rifa_id: str,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> NumerosResponse:
    """Grade completa de números com status (disponível/reservado/pago)."""
    return await svc.listar_numeros(rifa_id)


@router.post(
    "/comprar",
    response_model=PedidoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def criar_pedido(
    payload: PedidoCreate,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> PedidoResponse:
    """Reserva números e devolve QR Code Pix para pagamento."""
    try:
        return await svc.criar_pedido(payload)
    except NumeroIndisponivel as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OperacaoInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RifaNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Admin (protegido por ADMIN_TOKEN) ─────────────────────────


@router.post(
    "/admin",
    response_model=RifaResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def admin_criar_rifa(
    payload: RifaCreate,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> RifaResponse:
    """[Admin] Cria uma rifa e gera a grade de números."""
    return await svc.criar(payload)


@router.patch(
    "/admin/{rifa_id}",
    response_model=RifaResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_atualizar_rifa(
    rifa_id: str,
    payload: RifaUpdate,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> RifaResponse:
    """[Admin] Atualiza uma rifa."""
    try:
        return await svc.atualizar(rifa_id, payload)
    except RifaNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/admin/sortear",
    response_model=SorteioResponse,
    dependencies=[Depends(require_admin)],
)
async def admin_sortear(
    payload: SorteioRequest,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> SorteioResponse:
    """[Admin] Sorteia um número aleatório entre os pagos."""
    try:
        return await svc.disparar_sorteio(payload.rifa_id)
    except SorteioInvalido as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RifaNaoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
