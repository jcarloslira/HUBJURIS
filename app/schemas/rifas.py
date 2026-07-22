"""Schemas Pydantic do módulo de Rifas."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Rifas ─────────────────────────────────────────────────────


class RifaBase(BaseModel):
    """Campos comuns a criação/atualização/response de rifa."""

    titulo: str = Field(..., min_length=1, max_length=140)
    subtitulo: str | None = Field(None, max_length=200)
    descricao: str | None = None
    imagem_url: str | None = None
    preco_por_numero: Decimal = Field(..., gt=0)
    total_numeros: int = Field(100, gt=0, le=1_000_000)
    data_sorteio: datetime
    regulamento: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RifaCreate(RifaBase):
    """Schema de criação de rifa (admin)."""


class RifaUpdate(BaseModel):
    """Schema de atualização parcial de rifa."""

    titulo: str | None = Field(None, min_length=1, max_length=140)
    subtitulo: str | None = None
    descricao: str | None = None
    imagem_url: str | None = None
    preco_por_numero: Decimal | None = Field(None, gt=0)
    data_sorteio: datetime | None = None
    status: Literal["ativa", "encerrada", "sorteada", "cancelada"] | None = None
    regulamento: str | None = None


class RifaResponse(RifaBase):
    """Schema público de rifa."""

    id: str
    status: Literal["ativa", "encerrada", "sorteada", "cancelada"]
    numero_sorteado: int | None = None
    ganhador_nome: str | None = None
    numeros_vendidos: int = 0
    valor_arrecadado: Decimal = Decimal("0")
    created_at: datetime


# ── Números ───────────────────────────────────────────────────


class NumeroResponse(BaseModel):
    """Status de um número específico da rifa."""

    numero: int
    status: Literal["disponivel", "reservado", "pago"]


class NumerosResponse(BaseModel):
    """Lista de números e seus status."""

    rifa_id: str
    total: int
    disponiveis: int
    reservados: int
    pagos: int
    numeros: list[NumeroResponse]


# ── Pedido + Pix ──────────────────────────────────────────────


class PedidoCreate(BaseModel):
    """Dados do comprador para gerar pedido."""

    rifa_id: str
    numeros: list[int] = Field(..., min_length=1)
    comprador_nome: str = Field(..., min_length=1, max_length=120)
    comprador_telefone: str = Field(..., min_length=8, max_length=20)
    comprador_email: str | None = Field(None, max_length=120)

    @field_validator("numeros")
    @classmethod
    def _sem_duplicatas(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("Números duplicados no pedido")
        return v


class PixPayload(BaseModel):
    """QR Code Pix devolvido após criar pedido."""

    payment_id: str
    qr_code: str  # texto copia-cola
    qr_code_base64: str | None = None
    ticket_url: str | None = None
    valor_total: Decimal
    expires_at: datetime


class PedidoResponse(BaseModel):
    """Resumo do pedido criado."""

    pedido_id: str
    rifa_id: str
    numeros: list[int]
    valor_total: Decimal
    status: Literal["pendente", "pago", "expirado", "cancelado"]
    pix: PixPayload | None = None


# ── Sorteio ───────────────────────────────────────────────────


class SorteioRequest(BaseModel):
    """Disparo manual de sorteio (admin)."""

    rifa_id: str


class SorteioResponse(BaseModel):
    """Resultado do sorteio."""

    rifa_id: str
    numero_sorteado: int
    ganhador_nome: str | None = None
    ganhador_telefone: str | None = None
    sorteado_em: datetime
