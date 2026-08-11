"""Router de exportação de documentos — o "Gabinete Designer".

Recebe o conteúdo (Markdown) produzido por um agente e devolve o arquivo pronto
para download em Word, PDF ou Excel, JÁ no timbre do escritório logado. Também
expõe o CRUD do timbre (identidade visual). Requer login.
"""

import base64
import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.config import get_settings
from app.dependencies import get_current_user
from app.schemas.auth import AuthUser
from app.schemas.branding import Branding, BrandingResponse
from app.schemas.documentos import ExportarPayload
from app.services.branding import BrandingService
from app.services.contas import ContaService
from app.services.documentos import Timbre, gerar_docx, gerar_pdf, gerar_xlsx

router = APIRouter(prefix="/api/documentos", tags=["documentos"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _slug(nome: str) -> str:
    """Nome de arquivo seguro (ASCII, sem espaços)."""
    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    limpo = re.sub(r"[^\w\s-]", "", ascii_).strip().lower()
    limpo = re.sub(r"[\s_-]+", "-", limpo)
    return limpo[:60].strip("-") or "documento"


def _decodificar_logo(data_uri: str) -> bytes | None:
    """Extrai os bytes de um data URI base64 (ex.: 'data:image/png;base64,...')."""
    if not data_uri or "," not in data_uri:
        return None
    try:
        return base64.b64decode(data_uri.split(",", 1)[1])
    except Exception:  # noqa: BLE001 - logo inválido é ignorado
        return None


async def _escritorio_id(request: Request, user: AuthUser) -> str | None:
    """Resolve o escritório do usuário logado (ou None sem banco/erro)."""
    supabase = request.app.state.supabase
    if supabase is None:
        return None
    try:
        svc = ContaService(supabase, request.app.state.http_client, get_settings())
        perfil = await svc.perfil(user.id)
        return perfil.escritorio_id
    except Exception:  # noqa: BLE001 - contexto de conta é opcional
        return None


async def _timbre_do_usuario(request: Request, user: AuthUser) -> Timbre:
    """Monta o timbre (identidade) do escritório logado para aplicar na peça."""
    supabase = request.app.state.supabase
    escritorio_id = await _escritorio_id(request, user)
    if supabase is None or escritorio_id is None:
        return Timbre()
    try:
        marca = await BrandingService(supabase).obter(escritorio_id)
    except Exception:  # noqa: BLE001 - timbre indisponível não impede o export
        return Timbre()
    return Timbre(
        nome=marca.nome,
        subtitulo=marca.subtitulo,
        cor=marca.cor,
        rodape=marca.rodape,
        logo=_decodificar_logo(marca.logo),
    )


@router.get("/timbre", response_model=BrandingResponse)
async def obter_timbre(
    request: Request, user: Annotated[AuthUser, Depends(get_current_user)]
) -> BrandingResponse:
    """Retorna o timbre atual do escritório logado."""
    supabase = request.app.state.supabase
    escritorio_id = await _escritorio_id(request, user)
    if supabase is None or escritorio_id is None:
        return BrandingResponse()
    return await BrandingService(supabase).obter(escritorio_id)


@router.put("/timbre", response_model=BrandingResponse)
async def salvar_timbre(
    marca: Branding,
    request: Request,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> BrandingResponse:
    """Salva o timbre do escritório logado."""
    supabase = request.app.state.supabase
    escritorio_id = await _escritorio_id(request, user)
    if supabase is None or escritorio_id is None:
        return BrandingResponse(**marca.model_dump())
    return await BrandingService(supabase).salvar(escritorio_id, marca)


@router.post("/exportar")
async def exportar(
    payload: ExportarPayload,
    request: Request,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Response:
    """Gera o documento no formato pedido, no timbre do escritório, para download."""
    timbre = await _timbre_do_usuario(request, user)
    if payload.formato == "docx":
        dados = gerar_docx(payload.titulo, payload.conteudo, timbre=timbre)
    elif payload.formato == "pdf":
        dados = gerar_pdf(payload.titulo, payload.conteudo, timbre=timbre)
    else:
        dados = gerar_xlsx(payload.titulo, payload.conteudo)

    nome = f"{_slug(payload.titulo)}.{payload.formato}"
    return Response(
        content=dados,
        media_type=_MEDIA[payload.formato],
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
