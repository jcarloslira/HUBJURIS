"""Cliente HTTP para a W-API (WhatsApp)."""

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """Envia mensagens via W-API."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        """Inicializa o cliente com httpx e configurações.

        Args:
            http_client: Cliente HTTP assíncrono compartilhado.
            settings: Configurações da aplicação com credenciais W-API.
        """
        self.http = http_client
        self.base_url = settings.WAPI_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.WAPI_TOKEN}",
            "Content-Type": "application/json",
        }

    async def enviar_texto(self, telefone: str, mensagem: str) -> bool:
        """Envia uma mensagem de texto para o número informado.

        Args:
            telefone: Número do destinatário (apenas dígitos, com DDI).
            mensagem: Texto da mensagem.

        Returns:
            True se enviou com sucesso, False caso contrário.
        """
        url = f"{self.base_url}/send-text"
        payload = {
            "number": telefone,
            "text": mensagem,
        }

        try:
            response = await self.http.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Falha ao enviar mensagem para %s", telefone)
            return False
