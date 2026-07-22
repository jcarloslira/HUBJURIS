"""Webhook do Mercado Pago para confirmação de pagamentos Pix."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies_rifas import get_rifa_service
from app.services.rifas import PedidoNaoEncontrado, RifaService

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post(
    "/mercadopago",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def webhook_mercadopago(
    request: Request,
    svc: Annotated[RifaService, Depends(get_rifa_service)],
) -> None:
    """Recebe notificações do Mercado Pago.

    Valida o payload mínimo e atualiza o pedido relacionado.
    Em produção, configure o header `x-signature`/secreto do MP e valide aqui.
    """
    try:
        payload: Any = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    # Suporta tanto `data.id` quanto `resource` por query-string (legacy)
    payment_id: str | None = None
    if isinstance(payload, dict):
        if payload.get("type") == "payment" and isinstance(payload.get("data"), dict):
            payment_id = str(payload["data"].get("id"))
        elif payload.get("action") == "payment.created":
            payment_id = str(payload.get("data", {}).get("id"))

    if payment_id is None:
        # Merchant script também pode mandar só o ID no body
        payment_id = str(payload) if payload else None

    if not payment_id:
        raise HTTPException(status_code=400, detail="payment_id ausente")

    # Estratégia simples: consulta o pedido pelo mp_payment_id e marca como pago.
    # Se quiser paridade total, consultamos o pagamento no MP para confirmar status.
    db = svc._db  # noqa: SLF001 — uso controlado dentro do mesmo módulo de domínio
    pedido_rows = (
        await db.table("pedidos_rifa").select("id,status").eq("mp_payment_id", payment_id).execute()
    ).data
    if not pedido_rows:
        return None  # Não é nosso pagamento — ignora

    pedido_id = pedido_rows[0]["id"]
    if pedido_rows[0]["status"] == "pago":
        return None

    try:
        await svc.confirmar_pagamento(pedido_id)
    except PedidoNaoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return None


__all__ = ["router"]
