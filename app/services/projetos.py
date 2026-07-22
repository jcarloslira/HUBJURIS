"""Projetos (condomínios) multi-tenant: memória por projeto e auditoria.

Diferente do ``CondominioService`` da Espinha (single-tenant, admin), este
service é **escopado pelo escritório do usuário logado** (``escritorio_id`` do
JWT) e é o que alimenta o hub dos assinantes. Toda operação recebe o
``escritorio_id`` e nunca cruza a fronteira de outro tenant.
"""

from typing import Any

from supabase import AsyncClient

from app.schemas.projetos import FatoResponse, ProjetoCreate, ProjetoResponse


class ProjetoError(Exception):
    """Erro de negócio em projetos (não encontrado, falha de escrita...)."""

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


class ProjetoService:
    """CRUD de projetos/condomínios, memória (fatos) e trilha de auditoria.

    Sempre escopado por ``escritorio_id`` — o isolamento multi-tenant é
    garantido em cada query.
    """

    def __init__(self, supabase: AsyncClient) -> None:
        self._db = supabase

    # ── Projetos ────────────────────────────────────────────────

    async def listar(self, escritorio_id: str) -> list[ProjetoResponse]:
        """Lista os projetos do escritório, com a contagem de fatos de cada um."""
        result = (
            await self._db.table("condominios")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .order("nome")
            .execute()
        )
        rows = result.data or []
        contagem = await self._contar_fatos(escritorio_id)
        projetos: list[ProjetoResponse] = []
        for row in rows:
            projetos.append(
                ProjetoResponse(
                    id=str(row["id"]),
                    nome=row["nome"],
                    cnpj=row.get("cnpj"),
                    endereco=row.get("endereco"),
                    status=row.get("status") or "ativo",
                    total_fatos=contagem.get(str(row["id"]), 0),
                )
            )
        return projetos

    async def obter(self, escritorio_id: str, projeto_id: str) -> ProjetoResponse:
        """Retorna um projeto do escritório ou levanta 404."""
        row = await self._buscar_por_id(escritorio_id, projeto_id)
        if row is None:
            raise ProjetoError("Projeto não encontrado", status=404)
        contagem = await self._contar_fatos(escritorio_id)
        return ProjetoResponse(
            id=str(row["id"]),
            nome=row["nome"],
            cnpj=row.get("cnpj"),
            endereco=row.get("endereco"),
            status=row.get("status") or "ativo",
            total_fatos=contagem.get(str(row["id"]), 0),
        )

    async def criar(
        self, escritorio_id: str, payload: ProjetoCreate
    ) -> tuple[ProjetoResponse, bool]:
        """Cria um projeto — ou retorna o existente (get-or-create idempotente).

        O auto-registro do agente pode chamar isto várias vezes com o mesmo
        nome; nunca duplica. Retorna ``(projeto, ja_existia)``.
        """
        existente = await self._buscar_por_nome(escritorio_id, payload.nome)
        if existente is not None:
            return (
                ProjetoResponse(
                    id=str(existente["id"]),
                    nome=existente["nome"],
                    cnpj=existente.get("cnpj"),
                    endereco=existente.get("endereco"),
                    status=existente.get("status") or "ativo",
                ),
                True,
            )
        dados = {
            "escritorio_id": escritorio_id,
            "nome": payload.nome.strip(),
            "cnpj": payload.cnpj,
            "endereco": payload.endereco,
        }
        result = await self._db.table("condominios").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise ProjetoError("Falha ao criar o projeto", status=502)
        row = rows[0]
        return (
            ProjetoResponse(
                id=str(row["id"]),
                nome=row["nome"],
                cnpj=row.get("cnpj"),
                endereco=row.get("endereco"),
                status=row.get("status") or "ativo",
            ),
            False,
        )

    # ── Memória (fatos) ─────────────────────────────────────────

    async def listar_fatos(self, escritorio_id: str, projeto_id: str) -> list[FatoResponse]:
        """Fatos aprendidos sobre um projeto, do mais recente ao mais antigo."""
        if await self._buscar_por_id(escritorio_id, projeto_id) is None:
            raise ProjetoError("Projeto não encontrado", status=404)
        result = (
            await self._db.table("condominio_fatos")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .eq("condominio_id", projeto_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [
            FatoResponse(id=str(r["id"]), fato=r["fato"], origem=r.get("origem") or "agente")
            for r in (result.data or [])
        ]

    async def registrar_fato(
        self,
        escritorio_id: str,
        projeto_id: str,
        fato: str,
        origem: str = "agente",
    ) -> FatoResponse:
        """Salva um fato na memória de um projeto (verifica o tenant antes)."""
        if await self._buscar_por_id(escritorio_id, projeto_id) is None:
            raise ProjetoError("Projeto não encontrado", status=404)
        dados = {
            "escritorio_id": escritorio_id,
            "condominio_id": projeto_id,
            "fato": fato.strip(),
            "origem": origem,
        }
        result = await self._db.table("condominio_fatos").insert(dados).execute()
        rows = result.data or []
        if not rows:
            raise ProjetoError("Falha ao registrar o fato", status=502)
        row = rows[0]
        return FatoResponse(id=str(row["id"]), fato=row["fato"], origem=row.get("origem") or origem)

    # ── Auditoria ───────────────────────────────────────────────

    async def registrar_acao(
        self,
        *,
        escritorio_id: str,
        user_id: str | None,
        agente: str,
        ferramenta: str,
        argumentos: dict[str, Any],
        resultado: str,
    ) -> None:
        """Grava na trilha de auditoria uma ação executada por um agente."""
        await self._db.table("acoes_agente").insert(
            {
                "escritorio_id": escritorio_id,
                "user_id": user_id,
                "agente": agente,
                "ferramenta": ferramenta,
                "argumentos": argumentos,
                "resultado": resultado[:2000],
            }
        ).execute()

    # ── Internos ────────────────────────────────────────────────

    async def _buscar_por_id(self, escritorio_id: str, projeto_id: str) -> dict[str, Any] | None:
        result = (
            await self._db.table("condominios")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .eq("id", projeto_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None

    async def _buscar_por_nome(self, escritorio_id: str, nome: str) -> dict[str, Any] | None:
        """Busca case-insensitive por nome dentro do escritório."""
        alvo = nome.strip().lower()
        result = (
            await self._db.table("condominios")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        for row in result.data or []:
            if (row.get("nome") or "").strip().lower() == alvo:
                return row
        return None

    async def _contar_fatos(self, escritorio_id: str) -> dict[str, int]:
        """Mapa condominio_id → nº de fatos, numa só query por escritório."""
        result = (
            await self._db.table("condominio_fatos")
            .select("condominio_id")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        contagem: dict[str, int] = {}
        for row in result.data or []:
            cid = str(row.get("condominio_id"))
            contagem[cid] = contagem.get(cid, 0) + 1
        return contagem
