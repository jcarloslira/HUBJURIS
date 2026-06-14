"""Router de health check."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    """Verifica se a API está no ar."""
    return HealthResponse(status="ok", env=settings.APP_ENV)
