"""Config dos agentes em runtime: lê o banco, semeia padrões e permite editar.

Editar uma linha de ``agentes_config`` muda o comportamento do agente na próxima
resposta — sem redeploy. O código continua sendo a fonte dos PADRÕES, semeados
no boot para agentes que ainda não têm linha. Toda leitura degrada com
segurança: se o banco não responder, o chamador usa os padrões do código.
"""

from datetime import UTC, datetime
from typing import Any

from supabase import AsyncClient

from app.schemas.agentes import AgenteConfig, AgenteConfigUpdate

_TABELA = "agentes_config"


class AgenteConfigError(Exception):
    """Erro de negócio na config de agentes."""

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


class AgenteConfigService:
    """CRUD leve da configuração dos agentes (global, uma linha por slug)."""

    def __init__(self, supabase: AsyncClient) -> None:
        self._db = supabase

    async def listar(self) -> list[AgenteConfig]:
        """Configs do banco, ordenadas. Lista vazia se o banco não responder."""
        try:
            result = await self._db.table(_TABELA).select("*").order("ordem").execute()
            rows = result.data
        except Exception:  # noqa: BLE001 - banco indisponível → usa padrões do código
            return []
        if not isinstance(rows, list):
            return []
        configs: list[AgenteConfig] = []
        for row in rows:
            try:
                configs.append(AgenteConfig.model_validate(row))
            except Exception:  # noqa: BLE001 - linha malformada não derruba as demais
                continue
        return configs

    async def mapa(self) -> dict[str, AgenteConfig]:
        """Config por slug (para aplicar no agente que vai responder)."""
        return {c.slug: c for c in await self.listar()}

    async def atualizar(self, slug: str, update: AgenteConfigUpdate) -> AgenteConfig:
        """Atualiza os campos enviados de um agente e devolve a config nova."""
        campos: dict[str, Any] = {k: v for k, v in update.model_dump().items() if v is not None}
        if not campos:
            atual = await self._obter(slug)
            if atual is None:
                raise AgenteConfigError("Agente não encontrado", status=404)
            return atual
        campos["updated_at"] = datetime.now(UTC).isoformat()
        result = await self._db.table(_TABELA).update(campos).eq("slug", slug).execute()
        rows = result.data or []
        if not rows:
            raise AgenteConfigError("Agente não encontrado", status=404)
        return AgenteConfig.model_validate(rows[0])

    async def seed_defaults(self, defaults: list[AgenteConfig]) -> None:
        """Insere os agentes que ainda não existem na tabela (não sobrescreve)."""
        try:
            result = await self._db.table(_TABELA).select("slug").execute()
            rows = result.data if isinstance(result.data, list) else []
        except Exception:  # noqa: BLE001 - sem banco, não semeia
            return
        existentes = {r.get("slug") for r in rows}
        for cfg in defaults:
            if cfg.slug in existentes:
                continue
            try:
                await self._db.table(_TABELA).insert(cfg.model_dump()).execute()
            except Exception:  # noqa: BLE001 - falha de seed não derruba o boot
                continue

    async def _obter(self, slug: str) -> AgenteConfig | None:
        try:
            result = await self._db.table(_TABELA).select("*").eq("slug", slug).execute()
            rows = result.data or []
        except Exception:  # noqa: BLE001
            return None
        return AgenteConfig.model_validate(rows[0]) if rows else None
