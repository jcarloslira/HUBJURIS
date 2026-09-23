"""Serviço do timbre (identidade visual) por escritório."""

import base64

from app.schemas.branding import Branding, BrandingResponse
from app.services.documentos import Timbre
from supabase import AsyncClient


def decodificar_logo(data_uri: str) -> bytes | None:
    """Extrai os bytes de um data URI base64 (ex.: 'data:image/png;base64,...')."""
    if not data_uri or "," not in data_uri:
        return None
    try:
        return base64.b64decode(data_uri.split(",", 1)[1])
    except Exception:  # noqa: BLE001 - logo inválido é ignorado
        return None


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

    async def timbre(self, escritorio_id: str) -> Timbre:
        """O timbre pronto para carimbar um documento (logo já em bytes).

        Timbre indisponível não pode impedir a entrega: cai no padrão e o
        documento sai sem marca, em vez de a geração falhar.
        """
        try:
            marca = await self.obter(escritorio_id)
        except Exception:  # noqa: BLE001 - sem timbre o documento ainda vale
            return Timbre()
        return Timbre(
            nome=marca.nome,
            subtitulo=marca.subtitulo,
            cor=marca.cor,
            rodape=marca.rodape,
            logo=decodificar_logo(marca.logo),
        )

    async def salvar(self, escritorio_id: str, marca: Branding) -> BrandingResponse:
        """Grava o timbre do escritório e devolve o estado atualizado."""
        await self._db.table("escritorios").update({"branding": marca.model_dump()}).eq(
            "id", escritorio_id
        ).execute()
        return await self.obter(escritorio_id)
