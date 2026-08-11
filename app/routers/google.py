"""Router da conexão do Google Drive do escritório (via Composio, multi-tenant).

Cada escritório conecta o PRÓPRIO Drive: a identidade no Composio é o
``escritorio_id`` do usuário logado (JWT). Endpoints para status, link de
conexão, listagem de pastas e escolha da pasta-raiz do acervo de modelos.
"""

import asyncio
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.dependencies import get_current_user, get_supabase
from app.dependencies_google import get_composio_client
from app.routers.contas import get_conta_service
from app.schemas.auth import AuthUser
from app.schemas.google import AcervoPayload, ConectorStatus, PastaDrive, StatusDrive
from app.services.composio_drive import ComposioClient, ComposioError
from app.services.conectores import CONECTORES, client_para
from app.services.contas import ContaError, ContaService
from app.services.google_escritorio import GoogleEscritorioError, GoogleEscritorioService
from supabase import AsyncClient

router = APIRouter(prefix="/api/google", tags=["google"])


def get_google_service(
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
    composio: Annotated[ComposioClient | None, Depends(get_composio_client)],
) -> GoogleEscritorioService:
    """Service do Drive com o Supabase do lifespan e o cliente Composio."""
    return GoogleEscritorioService(supabase, composio)


_Svc = Annotated[GoogleEscritorioService, Depends(get_google_service)]
_User = Annotated[AuthUser, Depends(get_current_user)]
_Contas = Annotated[ContaService, Depends(get_conta_service)]


async def _escritorio_id(contas: ContaService, user: AuthUser) -> str:
    try:
        perfil = await contas.perfil(user.id)
    except ContaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return perfil.escritorio_id


def _erro(exc: GoogleEscritorioError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/status", response_model=StatusDrive, status_code=200)
async def status_conexao(user: _User, contas: _Contas, svc: _Svc) -> StatusDrive:
    """Estado do Drive do escritório logado: configurado, conectado e acervo."""
    return await svc.status(await _escritorio_id(contas, user))


@router.post("/conectar", status_code=200)
async def conectar(user: _User, contas: _Contas, svc: _Svc) -> dict[str, str]:
    """Gera o link "Conectar Google Drive" para o escritório logado."""
    escritorio_id = await _escritorio_id(contas, user)
    try:
        return {"redirect_url": await svc.link(escritorio_id)}
    except GoogleEscritorioError as exc:
        raise _erro(exc) from exc
    except ComposioError as exc:
        raise HTTPException(status_code=502, detail=f"Falha no Composio: {exc}") from exc


@router.get("/pastas", response_model=list[PastaDrive], status_code=200)
async def listar_pastas(
    user: _User, contas: _Contas, svc: _Svc, parent: str = "root"
) -> list[PastaDrive]:
    """Lista as pastas do Drive do escritório (para escolher o acervo)."""
    escritorio_id = await _escritorio_id(contas, user)
    try:
        return await svc.listar_pastas(escritorio_id, parent)
    except GoogleEscritorioError as exc:
        raise _erro(exc) from exc
    except ComposioError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao ler o Drive: {exc}") from exc


@router.put("/acervo", status_code=200)
async def definir_acervo(
    payload: AcervoPayload, user: _User, contas: _Contas, svc: _Svc
) -> dict[str, bool]:
    """Salva a pasta-raiz do acervo de modelos escolhida pelo escritório."""
    escritorio_id = await _escritorio_id(contas, user)
    await svc.definir_acervo(escritorio_id, payload.folder_id)
    return {"ok": True}


async def _status_conector(
    servico: str, nome: str, settings: Settings, http: httpx.AsyncClient, escritorio_id: str
) -> ConectorStatus:
    cli = client_para(settings, http, servico)
    conectado = False
    if cli is not None:
        try:
            conectado = await cli.conexao_ativa(escritorio_id)
        except Exception:  # noqa: BLE001 - rede não pode derrubar a lista
            conectado = False
    return ConectorStatus(
        servico=servico, nome=nome, configurado=cli is not None, conectado=conectado
    )


@router.get("/conectores", response_model=list[ConectorStatus], status_code=200)
async def listar_conectores(
    user: _User,
    contas: _Contas,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[ConectorStatus]:
    """Estado de todos os conectores (Drive, Agenda, Gmail, Docs, Sheets, Meet) do escritório."""
    escritorio_id = await _escritorio_id(contas, user)
    http = request.app.state.http_client
    return list(
        await asyncio.gather(
            *(
                _status_conector(servico, nome, settings, http, escritorio_id)
                for servico, (nome, _slug, _attr) in CONECTORES.items()
            )
        )
    )


@router.post("/conectar/{servico}", status_code=200)
async def conectar_servico(
    servico: str,
    user: _User,
    contas: _Contas,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Gera o link de conexão de um conector específico para o escritório logado."""
    escritorio_id = await _escritorio_id(contas, user)
    cli = client_para(settings, request.app.state.http_client, servico)
    if cli is None:
        raise HTTPException(status_code=503, detail="Conector indisponível ou não configurado")
    try:
        link = await cli.criar_link(escritorio_id)
    except ComposioError as exc:
        raise HTTPException(status_code=502, detail=f"Falha no Composio: {exc}") from exc
    return {"redirect_url": link.redirect_url}


@router.post("/desconectar/{servico}", status_code=200)
async def desconectar_servico(
    servico: str,
    user: _User,
    contas: _Contas,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    """Revoga a conexão de um conector do escritório (para reconectar/dar permissões)."""
    escritorio_id = await _escritorio_id(contas, user)
    cli = client_para(settings, request.app.state.http_client, servico)
    if cli is None:
        raise HTTPException(status_code=503, detail="Conector indisponível ou não configurado")
    try:
        removidas = await cli.desconectar(escritorio_id)
    except ComposioError as exc:
        raise HTTPException(status_code=502, detail=f"Falha no Composio: {exc}") from exc
    return {"desconectado": removidas > 0, "removidas": removidas}
