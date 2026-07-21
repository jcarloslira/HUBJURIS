"""Classe base para todos os agentes de IA do projeto."""

from collections.abc import AsyncIterator, Awaitable, Callable

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024


class BaseAgent:
    """Base para agentes LLM via Anthropic SDK.

    Subclasses devem definir `system_prompt` como constante no topo do
    próprio módulo e podem sobrescrever `model` e `max_tokens`.
    """

    system_prompt: str = ""
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __init__(self, client: AsyncAnthropic) -> None:
        """Inicializa o agente com um cliente Anthropic assíncrono.

        Args:
            client: Cliente Anthropic compartilhado da aplicação.
        """
        self.client = client

    async def processar(
        self,
        mensagem: str,
        historico: list[MessageParam] | None = None,
    ) -> str:
        """Processa uma mensagem do usuário e retorna a resposta do modelo.

        Args:
            mensagem: Mensagem atual do usuário.
            historico: Histórico de conversa como lista de `MessageParam`.

        Returns:
            Texto da resposta do modelo.
        """
        mensagens: list[MessageParam] = list(historico or [])
        mensagens.append({"role": "user", "content": mensagem})

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=mensagens,
        )
        bloco = response.content[0]
        return bloco.text if bloco.type == "text" else ""

    async def responder_stream(
        self,
        mensagens: list[MessageParam],
        modelo: str | None = None,
        referencia: str = "",
        on_usage: "Callable[[int, int], Awaitable[None]] | None" = None,
    ) -> AsyncIterator[str]:
        """Gera a resposta do modelo em streaming a partir do histórico completo.

        Args:
            mensagens: Histórico completo da conversa, incluindo a mensagem atual.
            modelo: Modelo a usar; se None, usa o padrão do agente.
            referencia: Bloco opcional de contexto (ex.: modelos do escritório)
                anexado ao system prompt para o agente seguir o padrão.
            on_usage: Callback opcional chamado ao fim do stream com os tokens
                de entrada e saída reais medidos pela API.

        Yields:
            Trechos de texto da resposta conforme são gerados.
        """
        system = f"{self.system_prompt}\n\n{referencia}" if referencia else self.system_prompt
        async with self.client.messages.stream(
            model=modelo or self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=mensagens,
        ) as stream:
            async for texto in stream.text_stream:
                yield texto
            if on_usage is not None:
                try:
                    final = await stream.get_final_message()
                    await on_usage(final.usage.input_tokens, final.usage.output_tokens)
                except Exception:  # noqa: BLE001 - medição não pode derrubar a resposta
                    pass
