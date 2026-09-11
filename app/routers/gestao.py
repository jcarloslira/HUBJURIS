"""API de gestão condominial do Hub — painel do dia, diário, ficha e cadastro.

Escopada pelo escritório do usuário logado (JWT). É a mesma camada que os
agentes usam pelas ferramentas ``hub_*``: tela e agente enxergam o mesmo Hub.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.config import get_settings
from app.dependencies import get_current_user, get_supabase
from app.routers.contas import get_conta_service
from app.schemas.auth import AuthUser
from app.schemas.gestao import AnotacaoCreate, CondominioUpdate
from app.services.contas import ContaError, ContaService
from app.services.gestao import GestaoError, GestaoService, hoje
from app.services.mcpai import MCPAIClient
from supabase import AsyncClient

router = APIRouter(prefix="/api/gestao", tags=["gestao"])


def get_gestao_service(
    request: Request,
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
) -> GestaoService:
    """Service de gestão com o Supabase e o conector EasyJur/Tiflux do app."""
    return GestaoService(supabase, MCPAIClient(request.app.state.http_client, get_settings()))


_Svc = Annotated[GestaoService, Depends(get_gestao_service)]
_User = Annotated[AuthUser, Depends(get_current_user)]
_Contas = Annotated[ContaService, Depends(get_conta_service)]


async def _escritorio(contas: ContaService, user: AuthUser) -> str:
    try:
        return (await contas.perfil(user.id)).escritorio_id
    except ContaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _erro(exc: GestaoError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/painel", status_code=200)
async def painel(
    user: _User,
    contas: _Contas,
    svc: _Svc,
    dia: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """O que aconteceu no dia + totais. Dispara a coleta do dia se ainda não houve."""
    escritorio_id = await _escritorio(contas, user)
    disparou = await svc.garantir_coleta_do_dia(escritorio_id)
    dados = await svc.painel(escritorio_id, dia)
    dados["coletando_agora"] = disparou
    return dados


@router.get("/condominios", status_code=200)
async def condominios(
    user: _User, contas: _Contas, svc: _Svc, busca: str = ""
) -> list[dict[str, Any]]:
    """Condomínios com a foto mais recente de cada um."""
    return await svc.listar_condominios(await _escritorio(contas, user), busca)


@router.get("/condominios/{condominio_id}", status_code=200)
async def ficha(condominio_id: str, user: _User, contas: _Contas, svc: _Svc) -> dict[str, Any]:
    """Ficha completa: cadastro, memória, evolução e eventos recentes."""
    try:
        return await svc.detalhe(await _escritorio(contas, user), condominio_id)
    except GestaoError as exc:
        raise _erro(exc) from exc


@router.patch("/condominios/{condominio_id}", status_code=200)
async def atualizar(
    condominio_id: str,
    payload: CondominioUpdate,
    user: _User,
    contas: _Contas,
    svc: _Svc,
) -> dict[str, Any]:
    """Atualiza o cadastro de gestão do condomínio."""
    try:
        return await svc.atualizar(
            await _escritorio(contas, user),
            condominio_id,
            payload.model_dump(exclude_unset=True),
        )
    except GestaoError as exc:
        raise _erro(exc) from exc


@router.post("/condominios/{condominio_id}/anotacoes", status_code=201)
async def anotar(
    condominio_id: str,
    payload: AnotacaoCreate,
    user: _User,
    contas: _Contas,
    svc: _Svc,
) -> dict[str, Any]:
    """Anotação do escritório no diário do condomínio."""
    try:
        return await svc.registrar_evento(
            await _escritorio(contas, user),
            condominio_id,
            titulo=payload.titulo,
            descricao=payload.descricao,
            dia=payload.dia,
        )
    except GestaoError as exc:
        raise _erro(exc) from exc


@router.get("/eventos", status_code=200)
async def eventos(
    user: _User,
    contas: _Contas,
    svc: _Svc,
    inicio: Annotated[date | None, Query()] = None,
    fim: Annotated[date | None, Query()] = None,
    condominio_id: str | None = None,
    fonte: str | None = None,
    tipo: str | None = None,
) -> dict[str, Any]:
    """Diário de um período (padrão: hoje), com resumo."""
    fim = fim or hoje()
    inicio = inicio or fim
    if inicio > fim:
        inicio, fim = fim, inicio
    return await svc.eventos(
        await _escritorio(contas, user),
        inicio=inicio,
        fim=fim,
        condominio_id=condominio_id,
        fonte=fonte,
        tipo=tipo,
    )


@router.post("/coletar", status_code=202)
async def coletar(user: _User, contas: _Contas, svc: _Svc) -> dict[str, Any]:
    """Dispara a coleta do EasyJur/Tiflux agora, em segundo plano."""
    escritorio_id = await _escritorio(contas, user)
    ultima = await svc.ultima_coleta(escritorio_id)
    if ultima and ultima.get("status") == "rodando" and not svc.travada(ultima):
        return {"status": "rodando", "desde": ultima.get("iniciada_em")}
    svc.disparar_coleta(escritorio_id)
    return {"status": "iniciada"}


@router.post("/cron", status_code=202)
async def coleta_agendada(
    svc: _Svc,
    x_cron_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Coleta agendada — chamada pelo pg_cron do Supabase (7h, 12h30 e 18h30).

    Sem login de usuário: autentica pelo token guardado no cofre do Supabase.
    Responde na hora e coleta em segundo plano (o servidor gratuito acorda com
    a própria chamada).
    """
    if not await svc.token_cron_valido(x_cron_token or ""):
        raise HTTPException(status_code=403, detail="Token da coleta agendada inválido.")
    return {"coletas_disparadas": len(await svc.coletar_agendado())}
