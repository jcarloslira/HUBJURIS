"""Entrypoint da aplicação FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import (
    admin_agentes,
    auth_admin,
    chat,
    condominios,
    contas,
    documentos,
    google,
    health,
    projetos,
    rifas,
    sdr,
    webhook,
    webhook_pix,
)
from app.services.agentes_config import AgenteConfigService
from app.services.chat import configs_padrao
from app.utils.supabase import create_supabase_client

_STATIC_DIR = Path(__file__).parent / "static"

# Caminhos liberados quando a requisição chega por um host externo
# (ex: túnel Cloudflare). Tudo o mais é bloqueado para fora — só funciona
# em localhost durante o desenvolvimento e demos presenciais.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/proposta",
        "/health",
        "/rifas",
        "/rifa",
        "/rifas/admin/painel",
        "/backend",
    }
)


def _is_local_host(host_header: str | None) -> bool:
    if not host_header:
        return True
    h = host_header.split(":", 1)[0].lower()
    return h in {"localhost", "127.0.0.1", "::1"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inicializa e finaliza recursos compartilhados da aplicação."""
    settings = get_settings()
    app.state.supabase = await create_supabase_client(settings)
    app.state.anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    # Semeia a config dos agentes (só os que faltam) — treinar sem redeploy.
    if app.state.supabase is not None:
        try:
            await AgenteConfigService(app.state.supabase).seed_defaults(configs_padrao())
        except Exception:  # noqa: BLE001 - seed é best-effort, não bloqueia o boot
            pass
    yield
    await app.state.http_client.aclose()
    await app.state.anthropic.close()


app = FastAPI(title="LexHub — Hub Jurídico de IA", lifespan=lifespan)


@app.middleware("http")
async def restrict_external_access(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Controla o acesso externo (fora de localhost).

    - Local (localhost): acesso total sempre — desenvolvimento e demo presencial.
    - Deploy com HUB_PUBLICO=true: acesso total também — os assinantes usam o hub.
    - Caso contrário (ex.: túnel só para a proposta): externo vê apenas a
      proposta institucional; chat e APIs ficam invisíveis para evitar consumo
      indevido de tokens.
    """
    if _is_local_host(request.headers.get("host")) or get_settings().HUB_PUBLICO:
        return await call_next(request)
    if request.url.path not in _PUBLIC_PATHS:
        return Response(status_code=404)
    return await call_next(request)


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(webhook.router)
app.include_router(sdr.router)
app.include_router(rifas.router)
app.include_router(webhook_pix.router)
app.include_router(auth_admin.router)
app.include_router(condominios.router)
app.include_router(google.router)
app.include_router(contas.router)
app.include_router(projetos.router)
app.include_router(admin_agentes.router)
app.include_router(documentos.router)

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve a interface do hub."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login_page() -> FileResponse:
    """Tela de entrada: login e criação de conta do escritório."""
    return FileResponse(_STATIC_DIR / "login.html")


@app.get("/proposta", include_in_schema=False)
async def proposta() -> FileResponse:
    """Serve a proposta confidencial do projeto."""
    return FileResponse(_STATIC_DIR / "proposta.html")


@app.get("/rifas", include_in_schema=False)
async def rifas_catalogo() -> FileResponse:
    """Catálogo público de rifas ativas."""
    return FileResponse(_STATIC_DIR / "catalog-rifas.html")


@app.get("/rifa", include_in_schema=False)
async def rifa_detalhe() -> FileResponse:
    """Página de compra de uma rifa (precisa de ?id=<rifa_id> ou ?slug=<slug>)."""
    return FileResponse(_STATIC_DIR / "rifa.html")


@app.get("/rifas/{slug}", include_in_schema=False)
async def rifa_detalhe_slug(slug: str) -> FileResponse:
    """Página de compra por slug amigável (ex: /rifas/hilux-diesel-2024)."""
    return FileResponse(_STATIC_DIR / "rifa.html")


@app.get("/rifas/admin/painel", include_in_schema=False)
async def rifas_admin() -> FileResponse:
    """Painel admin de rifas."""
    return FileResponse(_STATIC_DIR / "admin-rifas.html")


@app.get("/backend", include_in_schema=False)
async def backend_status() -> FileResponse:
    """Página que mostra o status do backend e todos os endpoints."""
    return FileResponse(_STATIC_DIR / "backend.html")
