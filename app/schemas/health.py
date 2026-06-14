"""Schemas do recurso de health check."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Resposta do endpoint de health check."""

    status: Literal["ok"]
    env: str
