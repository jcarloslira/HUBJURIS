"""Conector do Google Drive dos escritórios via Composio (M3).

O Composio fornece o OAuth gerenciado do Google Drive: cada escritório é um
`user_id`; o app gera um link de conexão, o usuário loga no Google, e depois
o app lê o Drive por aquele `user_id`. Esta camada implementa o contrato
``DriveConnector`` (de ``app.services.drive``) sem acoplar o resto do app à
API do Composio.
"""

import httpx
from pydantic import BaseModel

from app.services.drive import DriveEntry

_FOLDER_MIME = "application/vnd.google-apps.folder"


class ComposioError(Exception):
    """Falha ao falar com a API do Composio."""


class ConexaoLink(BaseModel):
    """Link de conexão do Google Drive gerado para um escritório."""

    redirect_url: str
    connected_account_id: str


class ComposioClient:
    """Cliente da API do Composio para o toolkit Google Drive."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str,
        auth_config_id: str,
    ) -> None:
        self._http = http
        self._headers = {"x-api-key": api_key}
        self._base = base_url.rstrip("/")
        self._auth_config_id = auth_config_id

    async def criar_link(self, user_id: str) -> ConexaoLink:
        """Gera o link "Conectar Google Drive" para um escritório (user_id).

        Args:
            user_id: Identificador do escritório no Composio.

        Returns:
            Link de redirecionamento + id da conexão criada.
        """
        resp = await self._http.post(
            f"{self._base}/connected_accounts/link",
            headers=self._headers,
            json={"auth_config_id": self._auth_config_id, "user_id": user_id},
        )
        dados = resp.json()
        if resp.status_code >= 400:
            raise ComposioError(str(dados.get("error") or dados))
        return ConexaoLink(
            redirect_url=dados["redirect_url"],
            connected_account_id=dados["connected_account_id"],
        )

    async def conexao_ativa(self, user_id: str) -> bool:
        """Indica se o escritório já conectou ESTE toolkit (filtra pelo auth config)."""
        resp = await self._http.get(
            f"{self._base}/connected_accounts",
            headers=self._headers,
            params={"user_ids": user_id, "auth_config_ids": self._auth_config_id},
        )
        itens = resp.json().get("items", [])
        return any(item.get("status") == "ACTIVE" for item in itens)

    async def executar_acao(self, tool: str, user_id: str, arguments: dict) -> dict:
        """Executa uma tool do Composio (ação externa) e devolve os dados."""
        return await self._execute(tool, user_id, arguments)

    async def _execute(self, tool: str, user_id: str, arguments: dict) -> dict:
        resp = await self._http.post(
            f"{self._base}/tools/execute/{tool}",
            headers=self._headers,
            json={"user_id": user_id, "arguments": arguments},
        )
        dados = resp.json()
        if not dados.get("successful", False):
            raise ComposioError(str(dados.get("error") or dados))
        return dados.get("data") or {}

    async def listar_filhos(self, user_id: str, pasta_id: str) -> list[DriveEntry]:
        """Lista pastas e arquivos dentro de uma pasta do Drive do escritório.

        Args:
            user_id: Escritório no Composio.
            pasta_id: ID da pasta pai (use ``"root"`` para a raiz).

        Returns:
            Itens diretos da pasta como ``DriveEntry``.
        """
        data = await self._execute(
            "GOOGLEDRIVE_LIST_FILES",
            user_id,
            {
                "q": f"'{pasta_id}' in parents and trashed = false",
                "pageSize": 200,
                "fields": "files(id,name,mimeType)",
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            },
        )
        return [
            DriveEntry(
                id=arquivo["id"],
                nome=arquivo.get("name", ""),
                is_folder=arquivo.get("mimeType") == _FOLDER_MIME,
                mime=arquivo.get("mimeType"),
            )
            for arquivo in data.get("files", [])
        ]

    async def ler_texto(self, user_id: str, file_id: str) -> str:
        """Lê o conteúdo textual de um arquivo do Drive do escritório.

        O ``PARSE_FILE`` do Composio devolve uma URL temporária (``s3url``);
        baixamos o conteúdo dela. Só funciona em arquivos da própria conta
        conectada — arquivos apenas compartilhados retornam erro.

        Args:
            user_id: Escritório no Composio.
            file_id: ID do arquivo no Drive.

        Returns:
            Texto do documento.
        """
        data = await self._execute("GOOGLEDRIVE_PARSE_FILE", user_id, {"file_id": file_id})
        s3url = (data.get("file") or {}).get("s3url")
        if not s3url:
            raise ComposioError("PARSE_FILE não retornou s3url")
        resp = await self._http.get(s3url)
        return resp.text


class ComposioDriveConnector:
    """Adapta o ``ComposioClient`` ao contrato ``DriveConnector``.

    Fixa o ``user_id`` do escritório, para que o restante do app trabalhe com
    a interface genérica ``listar_filhos(pasta_id)``.
    """

    def __init__(self, client: ComposioClient, user_id: str) -> None:
        self._client = client
        self._user_id = user_id

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        """Lista os itens de uma pasta do Drive do escritório fixado."""
        return await self._client.listar_filhos(self._user_id, pasta_id)

    async def ler_texto(self, file_id: str) -> str:
        """Lê o conteúdo de um arquivo do Drive do escritório fixado."""
        return await self._client.ler_texto(self._user_id, file_id)
