"""Entrypoint da aplicação FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import get_settings
from app.routers import chat, health, sdr, webhook
from app.utils.supabase import create_supabase_client

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Inicializa e finaliza recursos compartilhados da aplicação."""
    settings = get_settings()
    app.state.supabase = await create_supabase_client(settings)
    app.state.anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await app.state.http_client.aclose()
    await app.state.anthropic.close()


app = FastAPI(title="LexHub — Hub Jurídico de IA", lifespan=lifespan)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(webhook.router)
app.include_router(sdr.router)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve a interface do hub."""
    return FileResponse(_STATIC_DIR / "index.html")
