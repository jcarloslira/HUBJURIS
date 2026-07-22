"""Cliente HTTP do Mercado Pago para geração de Pix e consulta de pagamentos."""

from datetime import UTC
from decimal import Decimal

import httpx

from app.config import Settings


class MercadoPagoError(RuntimeError):
    """Erro retornado pela API do Mercado Pago."""


class MercadoPagoClient:
    """Wrapper minimalista sobre a API Pix do Mercado Pago.

    Usa PIX via `/v1/payments` com `payment_method_id= pix` e
    `point_of_interaction.transaction_data` para o QR Code.

    Docs: https://www.mercadopago.com.br/developers/pt/reference/payments/_payments/post
    """

    API_URL = "https://api.mercadopago.com/v1/payments"

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._token = settings.MERCADO_PAGO_ACCESS_TOKEN
        self._client = http_client

    @property
    def habilitado(self) -> bool:
        """Verifica se o token está configurado."""
        return bool(self._token)

    async def criar_pix(
        self,
        *,
        valor: Decimal,
        descricao: str,
        referencia_externa: str,
        nome_pagador: str,
        email_pagador: str | None = None,
        expiracao_segundos: int = 1800,
    ) -> dict:
        """Cria um pagamento Pix e devolve o objeto cru do Mercado Pago.

        Args:
            valor: Valor em reais (ex: Decimal("10.50")).
            descricao: Descrição que aparece no app do banco.
            referencia_externa: ID do nosso pedido (idempotência no MP).
            nome_pagador: Nome do comprador.
            email_pagador: Email opcional.
            expiracao_segundos: Tempo até o Pix expirar (default 30min).

        Returns:
            Dicionário retornado pelo MP — usamos `id`,
            `point_of_interaction.transaction_data.{qr_code,qr_code_base64,ticket_url}`.

        Raises:
            MercadoPagoError: Se a API retornar erro.
        """
        if not self.habilitado:
            raise MercadoPagoError("MERCADO_PAGO_ACCESS_TOKEN não configurado")

        valor_str = f"{valor:.2f}"  # noqa: F841 — mantido p/ debug/log futuro
        payload = {
            "transaction_amount": float(valor),
            "description": descricao,
            "payment_method_id": "pix",
            "external_reference": referencia_externa,
            "notification_url": "",  # configurado no dashboard do MP
            "date_of_expiration": _iso_em(expiracao_segundos),
            "payer": {
                "first_name": nome_pagador.split(" ", 1)[0],
                "last_name": nome_pagador.split(" ", 1)[-1] if " " in nome_pagador else "",
                **({"email": email_pagador} if email_pagador else {}),
            },
        }

        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Idempotency-Key": referencia_externa,
            "Content-Type": "application/json",
        }

        response = await self._client.post(
            self.API_URL, json=payload, headers=headers, timeout=15.0
        )

        if response.status_code >= 400:
            raise MercadoPagoError(f"Mercado Pago {response.status_code}: {response.text[:500]}")

        # Em ambiente de teste do MP o valor é exigido com 2 casas — normalizamos
        # o tipo de retorno pra Decimal/string; aqui devolvemos cru e a conversão
        # fica no service de rifas.
        return response.json()

    async def consultar_pagamento(self, payment_id: str | int) -> dict:
        """Consulta status de um pagamento existente."""
        if not self.habilitado:
            raise MercadoPagoError("MERCADO_PAGO_ACCESS_TOKEN não configurado")

        response = await self._client.get(
            f"{self.API_URL}/{payment_id}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=15.0,
        )
        if response.status_code >= 400:
            raise MercadoPagoError(f"Mercado Pago {response.status_code}: {response.text[:500]}")
        return response.json()


def _iso_em(segundos: int) -> str:
    """Retorna timestamp ISO 8601 com offset UTC, N segundos no futuro."""
    from datetime import datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=segundos)).isoformat()
