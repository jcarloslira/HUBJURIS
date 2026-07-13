"""Lógica de negócio da Espinha: escritório, condomínios, blocos e unidades."""

from supabase import AsyncClient

from app.schemas.condominios import (
    BlocoCreate,
    BlocoResponse,
    CondominioCreate,
    CondominioResponse,
    EscritorioResponse,
    EscritorioUpsert,
    UnidadeCreate,
    UnidadeResponse,
)


class CondominioError(Exception):
    """Erro de operação no módulo condominial."""


class CondominioService:
    """CRUD do escritório e da hierarquia condomínio → bloco → unidade.

    Single-tenant no MVP: existe um único escritório. Toda escrita já grava
    `escritorio_id`, deixando o caminho para multi-tenant (SaaS) sem migração.
    """

    def __init__(self, supabase: AsyncClient) -> None:
        self._db = supabase

    # ── Escritório (onboarding) ─────────────────────────────────

    async def obter_escritorio(self) -> EscritorioResponse | None:
        """Retorna o escritório persistido, ou None se ainda não houver onboarding."""
        result = await self._db.table("escritorios").select("*").limit(1).execute()
        rows = result.data or []
        return EscritorioResponse.model_validate(rows[0]) if rows else None

    async def upsert_escritorio(self, payload: EscritorioUpsert) -> EscritorioResponse:
        """Cria ou atualiza o escritório com os dados do onboarding."""
        dados = {
            "nome": payload.nome,
            "site": payload.site,
            "instagram": payload.instagram,
        }
        atual = await self._db.table("escritorios").select("id").limit(1).execute()
        existentes = atual.data or []
        if existentes:
            result = (
                await self._db.table("escritorios")
                .update(dados)
                .eq("id", existentes[0]["id"])
                .execute()
            )
        else:
            result = await self._db.table("escritorios").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise CondominioError("Falha ao salvar o escritório")
        return EscritorioResponse.model_validate(rows[0])

    async def _garantir_escritorio_id(self) -> str:
        """Retorna o id do escritório, criando um padrão se ainda não existir."""
        result = await self._db.table("escritorios").select("id").limit(1).execute()
        rows = result.data or []
        if rows:
            return str(rows[0]["id"])
        inserted = await self._db.table("escritorios").insert({"nome": "Meu Escritório"}).execute()
        novo = inserted.data or []
        if not novo:
            raise CondominioError("Falha ao inicializar o escritório")
        return str(novo[0]["id"])

    # ── Condomínios ─────────────────────────────────────────────

    async def criar_condominio(self, payload: CondominioCreate) -> CondominioResponse:
        """Cadastra um condomínio (cliente) vinculado ao escritório."""
        escritorio_id = await self._garantir_escritorio_id()
        dados = {
            "escritorio_id": escritorio_id,
            "nome": payload.nome,
            "cnpj": payload.cnpj,
            "endereco": payload.endereco,
        }
        result = await self._db.table("condominios").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise CondominioError("Falha ao criar o condomínio")
        return CondominioResponse.model_validate(rows[0])

    async def listar_condominios(self) -> list[CondominioResponse]:
        """Lista os condomínios cadastrados (alimenta o seletor de cliente)."""
        result = await self._db.table("condominios").select("*").order("nome").execute()
        return [CondominioResponse.model_validate(row) for row in (result.data or [])]

    # ── Blocos e unidades ───────────────────────────────────────

    async def criar_bloco(self, condominio_id: str, payload: BlocoCreate) -> BlocoResponse:
        """Cadastra um bloco de um condomínio."""
        dados = {"condominio_id": condominio_id, "nome": payload.nome}
        result = await self._db.table("blocos").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise CondominioError("Falha ao criar o bloco")
        return BlocoResponse.model_validate(rows[0])

    async def criar_unidade(self, bloco_id: str, payload: UnidadeCreate) -> UnidadeResponse:
        """Cadastra uma unidade de um bloco."""
        dados = {"bloco_id": bloco_id, "identificacao": payload.identificacao}
        result = await self._db.table("unidades").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise CondominioError("Falha ao criar a unidade")
        return UnidadeResponse.model_validate(rows[0])
