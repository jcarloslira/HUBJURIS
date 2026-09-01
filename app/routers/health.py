"""Router de health check."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


def _weasyprint_ok() -> bool:
    """Indica se o WeasyPrint consegue carregar (precisa das libs de sistema)."""
    try:
        import weasyprint  # noqa: F401 - só queremos saber se importa
    except Exception:  # noqa: BLE001 - ambiente sem as libs nativas
        return False
    return True


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Verifica se a API está no ar."""
    return HealthResponse(status="ok", env=settings.APP_ENV)


@router.get("/api/health/full")
async def health_full(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Health check detalhado — lista o que está e o que não está configurado."""
    return {
        "app": "rifavip",
        "env": settings.APP_ENV,
        "python": "3.12",
        "framework": "FastAPI",
        "supabase": {
            "configurado": bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY),
            "url": settings.SUPABASE_URL or None,
        },
        "anthropic": bool(settings.ANTHROPIC_API_KEY),
        "composio_drive": bool(settings.COMPOSIO_API_KEY),
        # Diz se o motor que renderiza as peças subiu de verdade: o WeasyPrint
        # exige libs de sistema (pango/cairo) que só existem se o Dockerfile rodar.
        "weasyprint": _weasyprint_ok(),
        "mcp_ai": bool(settings.MCP_AI_API_KEY),
        "mercado_pago": {
            "token_configurado": bool(settings.MERCADO_PAGO_ACCESS_TOKEN),
            "webhook_url": settings.MERCADO_PAGO_WEBHOOK_URL or None,
        },
        "admin_token": bool(settings.ADMIN_TOKEN),
        "whatsapp_wapi": bool(settings.WAPI_TOKEN),
        "rifas_endpoints": {
            "listar": "GET /api/rifas",
            "detalhes": "GET /api/rifas/{id}",
            "numeros": "GET /api/rifas/{id}/numeros",
            "comprar": "POST /api/rifas/comprar",
            "admin_criar": "POST /api/rifas/admin",
            "admin_atualizar": "PATCH /api/rifas/admin/{id}",
            "admin_sortear": "POST /api/rifas/admin/sortear",
            "webhook_pix": "POST /webhook/mercadopago",
            "auth_admin": "POST /api/auth/admin",
        },
    }
