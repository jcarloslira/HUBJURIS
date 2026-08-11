"""Schemas do timbre (identidade visual) do escritório."""

from pydantic import BaseModel, ConfigDict, Field


class Branding(BaseModel):
    """Identidade visual aplicada às peças exportadas (Word/PDF)."""

    model_config = ConfigDict(extra="ignore")

    subtitulo: str = Field("", max_length=160, description="Linha sob o nome (OAB, área).")
    cor: str = Field("#9A6A3A", max_length=9, description="Cor do timbre em hex (#RRGGBB).")
    rodape: str = Field("", max_length=300, description="Rodapé de confidencialidade.")
    logo: str = Field("", description="Logo como data URI base64 (opcional).")


class BrandingResponse(Branding):
    """Timbre + o nome do escritório (que vem da própria conta)."""

    nome: str = ""
