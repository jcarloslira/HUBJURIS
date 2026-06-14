"""Schemas para o payload de webhook da W-API."""

from pydantic import BaseModel, ConfigDict


class WAPIMessageKey(BaseModel):
    """Identificador da mensagem."""

    id: str | None = None
    fromMe: bool = False
    remoteJid: str = ""


class WAPIMessageContent(BaseModel):
    """Conteúdo da mensagem recebida."""

    conversation: str | None = None
    extendedTextMessage: dict | None = None


class WAPIMessageData(BaseModel):
    """Dados da mensagem recebida via webhook."""

    key: WAPIMessageKey | None = None
    pushName: str | None = None
    message: WAPIMessageContent | None = None
    messageType: str | None = None

    # Campos alternativos (depende do provedor)
    from_: str | None = None
    body: str | None = None
    sender: str | None = None
    phone: str | None = None
    text: str | None = None
    number: str | None = None
    name: str | None = None

    model_config = ConfigDict(extra="allow")

    def extrair_texto(self) -> str | None:
        """Extrai o texto da mensagem, independente do formato do provedor."""
        if self.body:
            return self.body
        if self.text:
            return self.text
        if self.message:
            if self.message.conversation:
                return self.message.conversation
            if self.message.extendedTextMessage:
                return self.message.extendedTextMessage.get("text")
        return None

    def extrair_telefone(self) -> str | None:
        """Extrai o número de telefone do payload."""
        if self.phone:
            return self.phone.replace("+", "").replace("-", "").replace(" ", "")
        if self.number:
            return self.number.replace("+", "").replace("-", "").replace(" ", "")
        if self.from_:
            return self.from_.split("@")[0]
        if self.sender:
            return self.sender.split("@")[0]
        if self.key and self.key.remoteJid:
            return self.key.remoteJid.split("@")[0]
        return None

    def extrair_nome(self) -> str | None:
        """Extrai o nome do contato."""
        return self.name or self.pushName

    def eh_mensagem_propria(self) -> bool:
        """Verifica se a mensagem foi enviada pelo próprio bot."""
        if self.key and self.key.fromMe:
            return True
        return False

    def eh_grupo(self) -> bool:
        """Verifica se a mensagem veio de um grupo."""
        jid = ""
        if self.key and self.key.remoteJid:
            jid = self.key.remoteJid
        elif self.from_:
            jid = self.from_
        return jid.endswith("@g.us")


class WAPIWebhookPayload(BaseModel):
    """Payload do webhook da W-API. Aceita formatos flexíveis."""

    event: str | None = None
    instance: str | None = None
    data: WAPIMessageData | None = None

    # Campos de nível raiz (alguns provedores enviam direto)
    body: str | None = None
    phone: str | None = None
    text: str | None = None
    number: str | None = None
    name: str | None = None
    from_: str | None = None
    fromMe: bool | None = None
    message: dict | None = None

    model_config = ConfigDict(extra="allow")

    def resolver_dados(self) -> WAPIMessageData:
        """Resolve os dados da mensagem independente do formato do payload.

        Provedores diferentes enviam payloads em formatos distintos.
        Este método normaliza para WAPIMessageData.
        """
        if self.data:
            return self.data

        return WAPIMessageData(
            body=self.body or self.text,
            phone=self.phone or self.number,
            text=self.text or self.body,
            number=self.number or self.phone,
            name=self.name,
            from_=self.from_,
            key=WAPIMessageKey(fromMe=self.fromMe or False),
            message=(WAPIMessageContent(**self.message) if self.message else None),
        )
