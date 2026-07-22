"""Conexão do Google Drive por escritório (Composio multi-tenant).

A identidade no Composio é o próprio ``escritorio_id`` — assim cada escritório
conecta o seu Drive sem colidir com os outros. A pasta-raiz do acervo de modelos
escolhida por cada escritório fica em ``escritorios.acervo_folder_id``.
"""

from supabase import AsyncClient

from app.schemas.google import PastaDrive, StatusDrive
from app.services.composio_drive import ComposioClient


class GoogleEscritorioError(Exception):
    """Erro de negócio na conexão do Drive (ex.: Composio não configurado)."""

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


class GoogleEscritorioService:
    """Status, link de conexão, listagem de pastas e escolha do acervo — por escritório."""

    def __init__(self, supabase: AsyncClient, composio: ComposioClient | None) -> None:
        self._db = supabase
        self._composio = composio

    async def status(self, escritorio_id: str) -> StatusDrive:
        """Diz se o Composio está configurado, se o Drive está conectado e o acervo."""
        if self._composio is None:
            return StatusDrive(configurado=False, conectado=False)
        try:
            conectado = await self._composio.conexao_ativa(escritorio_id)
        except Exception:  # noqa: BLE001 - falha de rede não pode derrubar o status
            conectado = False
        acervo = await self.acervo_de(escritorio_id)
        return StatusDrive(
            configurado=True,
            conectado=conectado,
            acervo_definido=acervo is not None,
            acervo_folder_id=acervo,
        )

    async def link(self, escritorio_id: str) -> str:
        """Gera o link de conexão do Google Drive para o escritório."""
        conn = await self._exigir_composio().criar_link(escritorio_id)
        return conn.redirect_url

    async def listar_pastas(self, escritorio_id: str, parent: str = "root") -> list[PastaDrive]:
        """Lista as pastas do Drive do escritório (para escolher o acervo)."""
        itens = await self._exigir_composio().listar_filhos(escritorio_id, parent)
        return [PastaDrive(id=e.id, nome=e.nome) for e in itens if e.is_folder]

    async def definir_acervo(self, escritorio_id: str, folder_id: str) -> None:
        """Salva a pasta-raiz do acervo de modelos do escritório."""
        await self._db.table("escritorios").update({"acervo_folder_id": folder_id}).eq(
            "id", escritorio_id
        ).execute()

    async def acervo_de(self, escritorio_id: str) -> str | None:
        """Pasta-raiz do acervo do escritório, ou None se ainda não escolhida."""
        result = (
            await self._db.table("escritorios")
            .select("acervo_folder_id")
            .eq("id", escritorio_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return (rows[0].get("acervo_folder_id") if rows else None) or None

    def _exigir_composio(self) -> ComposioClient:
        if self._composio is None:
            raise GoogleEscritorioError(
                "Google Drive indisponível — Composio não configurado no servidor",
                status=503,
            )
        return self._composio
