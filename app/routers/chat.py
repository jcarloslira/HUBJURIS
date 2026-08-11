"""Router do chat com os agentes do hub."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.agents.ferramentas import FERRAMENTAS_SISTEMA, montar_executor
from app.agents.ferramentas_google import (
    ferramentas_google_disponiveis,
    montar_handlers_google,
)
from app.config import Settings, get_settings
from app.dependencies_google import USER_ID_PADRAO, get_composio_client
from app.schemas.chat import AgenteInfo, ChatRequest
from app.schemas.contas import PerfilResponse
from app.services import chat as chat_service
from app.services.agentes_config import AgenteConfigService
from app.services.composio_drive import ComposioClient, ComposioDriveConnector
from app.services.conectores import client_para
from app.services.conhecimento import ConhecimentoService, formatar_conhecimento
from app.services.contas import ContaService
from app.services.google_escritorio import GoogleEscritorioService
from app.services.projetos import ProjetoService

_SERVICOS_ACAO = ("agenda", "gmail", "docs", "sheets")

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/agentes", response_model=list[AgenteInfo], status_code=200)
async def listar_agentes(request: Request) -> list[AgenteInfo]:
    """Lista os agentes do hub — config do banco, com fallback para o código."""
    supabase = request.app.state.supabase
    if supabase is not None:
        configs = await AgenteConfigService(supabase).listar()
        if configs:
            return [
                AgenteInfo(slug=c.slug, nome=c.nome, descricao=c.descricao, icone=c.icone)
                for c in configs
                if c.ativo
            ]
    return chat_service.listar_agentes()


async def _resolver_perfil(
    request: Request, authorization: str | None
) -> tuple[ContaService, PerfilResponse] | None:
    """Valida o Bearer e devolve (service de contas, perfil), ou None.

    Token ausente/ inválido não bloqueia o chat (o app local segue útil); só
    desliga a medição de uso e as ferramentas de sistema (que precisam do
    escritório).
    """
    supabase = request.app.state.supabase
    if supabase is None or not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        resp = await supabase.auth.get_user(token)
        if resp is None or resp.user is None:
            return None
        svc = ContaService(supabase, request.app.state.http_client, get_settings())
        perfil = await svc.perfil(str(resp.user.id))
    except Exception:  # noqa: BLE001 - contexto de conta é opcional
        return None
    return svc, perfil


def _montar_registro_uso(svc: ContaService, perfil: PerfilResponse):
    """Callback que grava o consumo real de tokens do escritório."""

    async def registrar(agente: str, modelo: str, tokens_in: int, tokens_out: int) -> None:
        try:
            await svc.registrar_uso(
                escritorio_id=perfil.escritorio_id,
                user_id=perfil.user_id,
                agente=agente,
                modelo=modelo,
                tokens_entrada=tokens_in,
                tokens_saida=tokens_out,
            )
        except Exception:  # noqa: BLE001
            pass

    return registrar


def _montar_ferramentas(request: Request, perfil: PerfilResponse, settings: Settings):
    """Ferramentas do Supervisor: internas (condomínio, memória) + ações Google.

    As ações Google (Agenda, Gmail, Docs, Sheets) só entram para os serviços
    configurados; todas escopadas ao escritório do usuário.
    """
    projetos = ProjetoService(request.app.state.supabase)
    http = request.app.state.http_client
    clients = {s: client_para(settings, http, s) for s in _SERVICOS_ACAO}
    executar = montar_executor(
        projetos,
        escritorio_id=perfil.escritorio_id,
        user_id=perfil.user_id,
        extra_handlers=montar_handlers_google(clients, perfil.escritorio_id),
    )
    tools = [*FERRAMENTAS_SISTEMA, *ferramentas_google_disponiveis(clients)]
    return tools, executar


@router.post("/chat", status_code=200)
async def conversar(
    payload: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    composio: Annotated[ComposioClient | None, Depends(get_composio_client)],
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """Envia o histórico ao agente escolhido (ou roteia via Supervisor) em streaming.

    Com Composio configurado + pasta do acervo, o especialista é aterrado nos
    modelos do escritório. Com token de sessão, o consumo real de tokens é
    gravado para o painel de Uso.
    """
    if not chat_service.agente_existe(payload.agente):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agente desconhecido: {payload.agente}",
        )

    contexto = await _resolver_perfil(request, authorization)
    on_usage = None
    ferramentas = executar_ferramenta = None
    conector = None
    acervo_raiz = None
    if contexto is not None:
        svc, perfil = contexto
        on_usage = _montar_registro_uso(svc, perfil)
        ferramentas, executar_ferramenta = _montar_ferramentas(request, perfil, settings)
        # Grounding por escritório: o agente se baseia no Drive DELE (entity =
        # escritorio_id) e na pasta de acervo que ESTE escritório escolheu.
        if composio is not None:
            acervo_raiz = await GoogleEscritorioService(
                request.app.state.supabase, composio
            ).acervo_de(perfil.escritorio_id)
            if acervo_raiz:
                conector = ComposioDriveConnector(composio, perfil.escritorio_id)

    # Fallback single-tenant (sem login): usa o acervo global, se configurado.
    if conector is None and composio is not None and settings.COMPOSIO_ACERVO_FOLDER_ID:
        conector = ComposioDriveConnector(composio, USER_ID_PADRAO)
        acervo_raiz = settings.COMPOSIO_ACERVO_FOLDER_ID

    supabase = request.app.state.supabase
    configs = await AgenteConfigService(supabase).mapa() if supabase is not None else None

    # Busca na base de conhecimento (RAG) escopada ao escritório logado (ou só o
    # acervo global quando não há login). Fica como closure para o chat service
    # ficar desacoplado do Supabase/HTTP.
    buscar_conhecimento = None
    if supabase is not None:
        escritorio_id = contexto[1].escritorio_id if contexto is not None else None
        kb = ConhecimentoService(supabase, request.app.state.http_client, settings)

        async def buscar_conhecimento(consulta: str) -> str:
            trechos = await kb.buscar(consulta, escritorio_id)
            return formatar_conhecimento(trechos)

    return StreamingResponse(
        chat_service.gerar_resposta_stream(
            payload,
            request.app.state.anthropic,
            conector=conector,
            acervo_raiz=acervo_raiz,
            on_usage=on_usage,
            ferramentas=ferramentas,
            executar_ferramenta=executar_ferramenta,
            configs=configs,
            buscar_conhecimento=buscar_conhecimento,
        ),
        media_type="text/plain; charset=utf-8",
    )
