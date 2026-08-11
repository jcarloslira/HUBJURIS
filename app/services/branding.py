"""Serviço do timbre (identidade visual) por escritório."""

from app.schemas.branding import Branding, BrandingResponse
from supabase import AsyncClient


class BrandingService:
    """Lê e grava o timbre do escritório (coluna ``branding`` de ``escritorios``)."""

    def __init__(self, supabase: AsyncClient) -> None:
        self._db = supabase

    async def obter(self, escritorio_id: str) -> BrandingResponse:
        """Retorna o timbre do escritório (com defaults) + o nome da conta."""
        res = (
            await self._db.table("escritorios")
            .select("nome, branding")
            .eq("id", escritorio_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return BrandingResponse()
        row = rows[0]
        marca = Branding(**(row.get("branding") or {}))
        return BrandingResponse(nome=row.get("nome") or "", **marca.model_dump())

    async def salvar(self, escritorio_id: str, marca: Branding) -> BrandingResponse:
        """Grava o timbre do escritório e devolve o estado atualizado."""
        await self._db.table("escritorios").update({"branding": marca.model_dump()}).eq(
            "id", escritorio_id
        ).execute()
        return await self.obter(escritorio_id)
