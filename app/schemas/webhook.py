"""Schemas para o payload de webhook da Evolution API v2."""

from pydantic import BaseModel


class EvolutionMessageKey(BaseModel):
    """Identificador da mensagem no WhatsApp."""

    remoteJid: str
    fromMe: bool = False
    id: str | None = None


class EvolutionTextMessage(BaseModel):
    """Conteúdo de texto da mensagem."""

    conversation: str | None = None


class EvolutionExtendedText(BaseModel):
    """Texto estendido (mensagem com preview de link, etc)."""

    text: str | None = None


class EvolutionMessageContent(BaseModel):
    """Conteúdo da mensagem — pode ser texto simples ou estendido."""

    conversation: str | None = None
    extendedTextMessage: EvolutionExtendedText | None = None


class EvolutionMessageData(BaseModel):
    """Dados da mensagem recebida."""

    key: EvolutionMessageKey
    pushName: str | None = None
    message: EvolutionMessageContent | None = None

    def extrair_texto(self) -> str | None:
        """Extrai o texto da mensagem, independente do formato."""
        if self.message is None:
            return None
        if self.message.conversation:
            return self.message.conversation
        if self.message.extendedTextMessage and self.message.extendedTextMessage.text:
            return self.message.extendedTextMessage.text
        return None

    def extrair_telefone(self) -> str:
        """Extrai o número de telefone do remoteJid."""
        return self.key.remoteJid.split("@")[0]


class EvolutionWebhookPayload(BaseModel):
    """Payload completo do webhook da Evolution API."""

    instance: str | None = None
    event: str | None = None
    data: EvolutionMessageData
