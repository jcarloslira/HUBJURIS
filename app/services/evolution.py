"""Cliente HTTP para a Evolution API (WhatsApp)."""

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class EvolutionClient:
    """Envia mensagens via Evolution API v2."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        """Inicializa o cliente com httpx e configurações.

        Args:
            http_client: Cliente HTTP assíncrono compartilhado.
            settings: Configurações da aplicação com credenciais Evolution.
        """
        self.http = http_client
        self.base_url = settings.EVOLUTION_API_URL.rstrip("/")
        self.instance = settings.EVOLUTION_INSTANCE
        self.headers = {"apikey": settings.EVOLUTION_API_KEY}

    async def enviar_texto(self, telefone: str, mensagem: str) -> bool:
        """Envia uma mensagem de texto para o número informado.

        Args:
            telefone: Número do destinatário (apenas dígitos, com DDI).
            mensagem: Texto da mensagem.

        Returns:
            True se enviou com sucesso, False caso contrário.
        """
        url = f"{self.base_url}/message/sendText/{self.instance}"
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

    async def enviar_reacao(self, telefone: str, message_id: str, emoji: str = "👍") -> bool:
        """Envia uma reação a uma mensagem.

        Args:
            telefone: Número do remetente.
            message_id: ID da mensagem para reagir.
            emoji: Emoji da reação.

        Returns:
            True se enviou com sucesso.
        """
        url = f"{self.base_url}/message/sendReaction/{self.instance}"
        payload = {
            "key": {
                "remoteJid": f"{telefone}@s.whatsapp.net",
                "id": message_id,
            },
            "reaction": emoji,
        }

        try:
            response = await self.http.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            logger.exception("Falha ao enviar reação para %s", telefone)
            return False
