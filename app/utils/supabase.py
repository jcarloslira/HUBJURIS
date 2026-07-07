"""Helper de criação do cliente Supabase assíncrono."""

from supabase import AsyncClient, acreate_client

from app.config import Settings


async def create_supabase_client(settings: Settings) -> AsyncClient | None:
    """Cria o cliente Supabase assíncrono usado pela aplicação.

    Usa a chave anônima por padrão; operações privilegiadas devem criar um
    cliente próprio com a service role key, nunca expor essa chave.

    Args:
        settings: Configurações da aplicação.

    Returns:
        Cliente Supabase assíncrono, ou None quando não configurado (modo demo).
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        return None
    return await acreate_client(
        settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
    )
