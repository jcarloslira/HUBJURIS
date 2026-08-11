"""Cliente REST do mcp.ai ("Banco MCP") — EasyJur (jurídico) e Tiflux (helpdesk).

Cada MCP do mcp.ai expõe uma REST própria em ``https://api.mcp.ai/api/<slug>/...``;
chamamos com a Workspace API key (Bearer). A resposta padrão é
``{"ok": true, "tool": "...", "result": {...}}``. Esta camada isola o resto do
app do provedor — os agentes só veem ferramentas de negócio.
"""

import httpx

from app.config import Settings


class MCPAIError(Exception):
    """Falha ao chamar a REST do mcp.ai."""


class MCPAIClient:
    """Executa endpoints REST do mcp.ai (EasyJur/Tiflux) com a Workspace API key."""

    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self._http = http
        self._key = settings.MCP_AI_API_KEY
        self._base = settings.MCP_AI_BASE_URL.rstrip("/")

    @property
    def ativo(self) -> bool:
        """Indica se o conector está configurado (há API key)."""
        return bool(self._key)

    async def chamar(self, path: str, args: dict | None = None) -> dict:
        """Chama um endpoint do mcp.ai e devolve o ``result``.

        Args:
            path: Caminho do endpoint, ex.: ``/api/easyjur/list/processos``.
            args: Corpo JSON (parâmetros do endpoint).

        Returns:
            O conteúdo de ``result`` da resposta.

        Raises:
            MCPAIError: Em erro HTTP ou resposta ``ok: false``.
        """
        resp = await self._http.post(
            f"{self._base}{path}",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json=args or {},
            timeout=45,
        )
        try:
            dados = resp.json()
        except Exception as exc:  # noqa: BLE001 - resposta não-JSON vira erro claro
            raise MCPAIError(f"Resposta inválida do mcp.ai ({resp.status_code})") from exc
        if resp.status_code >= 400 or dados.get("ok") is False:
            raise MCPAIError(str(dados.get("error") or dados))
        return dados.get("result", dados)
