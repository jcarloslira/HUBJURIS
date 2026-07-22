"""Classe base para todos os agentes de IA do projeto."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 1024

# Teto de idas ao modelo num único turno com ferramentas (evita loop infinito).
MAX_ITERACOES_FERRAMENTAS = 5


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
        ferramentas: list[dict[str, Any]] | None = None,
        executar_ferramenta: "Callable[[str, dict[str, Any]], Awaitable[str]] | None" = None,
    ) -> AsyncIterator[str]:
        """Gera a resposta do modelo em streaming a partir do histórico completo.

        Quando ``ferramentas`` e ``executar_ferramenta`` são informados, roda um
        laço agêntico: se o modelo pedir uma ferramenta, ela é executada, o
        resultado volta como ``tool_result`` e o modelo continua — até responder
        sem pedir mais ferramentas (ou atingir ``MAX_ITERACOES_FERRAMENTAS``). O
        consumo de tokens é somado entre as passadas e reportado uma única vez.

        Sem ferramentas, o comportamento é idêntico ao de um streaming simples.

        Args:
            mensagens: Histórico completo da conversa, incluindo a mensagem atual.
            modelo: Modelo a usar; se None, usa o padrão do agente.
            referencia: Bloco opcional de contexto (ex.: modelos do escritório)
                anexado ao system prompt para o agente seguir o padrão.
            on_usage: Callback opcional chamado ao fim com os tokens totais
                (entrada, saída) reais medidos pela API.
            ferramentas: Schemas de ferramentas (tool-use) disponíveis ao modelo.
            executar_ferramenta: Callback ``(nome, entrada) -> texto`` que executa
                a ferramenta e devolve o resultado para o ``tool_result``.

        Yields:
            Trechos de texto da resposta conforme são gerados.
        """
        system = f"{self.system_prompt}\n\n{referencia}" if referencia else self.system_prompt
        usa_tools = bool(ferramentas) and executar_ferramenta is not None
        # Só materializamos a mensagem final quando ela é necessária (medir uso ou
        # decidir o laço de ferramentas). Sem isso, é um streaming simples idêntico.
        precisa_final = usa_tools or on_usage is not None
        historico: list[MessageParam] = list(mensagens)
        tokens_in = tokens_out = 0

        for _ in range(MAX_ITERACOES_FERRAMENTAS if usa_tools else 1):
            extra: dict[str, Any] = {"tools": ferramentas} if usa_tools else {}
            async with self.client.messages.stream(
                model=modelo or self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=historico,
                **extra,
            ) as stream:
                async for texto in stream.text_stream:
                    yield texto
                final = await stream.get_final_message() if precisa_final else None

            if final is None:
                break
            tokens_in += final.usage.input_tokens
            tokens_out += final.usage.output_tokens

            if not (usa_tools and final.stop_reason == "tool_use"):
                break

            assert executar_ferramenta is not None  # garantido por usa_tools
            historico.append({"role": "assistant", "content": final.content})
            resultados: list[dict[str, Any]] = []
            for bloco in final.content:
                if getattr(bloco, "type", None) == "tool_use":
                    saida = await executar_ferramenta(bloco.name, dict(bloco.input))
                    resultados.append(
                        {"type": "tool_result", "tool_use_id": bloco.id, "content": saida}
                    )
            historico.append({"role": "user", "content": resultados})

        if on_usage is not None:
            try:
                await on_usage(tokens_in, tokens_out)
            except Exception:  # noqa: BLE001 - medição não pode derrubar a resposta
                pass
