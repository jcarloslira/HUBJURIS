"""Lógica de negócio do módulo de rifas."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from supabase import AsyncClient

from app.schemas.rifas import (
    NumeroResponse,
    NumerosResponse,
    PedidoCreate,
    PedidoResponse,
    PixPayload,
    RifaCreate,
    RifaResponse,
    RifaUpdate,
    SorteioResponse,
)
from app.services.mercadopago import MercadoPagoClient

PIX_EXPIRACAO_SEGUNDOS = 1800  # 30 min
RESERVA_EXPIRACAO_SEGUNDOS = 900  # 15 min


class RifaService:
    """Operações de rifas, números e pedidos Pix."""

    def __init__(
        self,
        supabase: AsyncClient,
        mp: MercadoPagoClient,
        *,
        webhook_url: str = "",
    ) -> None:
        self._db = supabase
        self._mp = mp
        self._webhook_url = webhook_url

    # ── Catálogo ────────────────────────────────────────────────

    async def listar_ativas(self) -> list[RifaResponse]:
        """Lista rifas ativas e encerradas para o catálogo público."""
        result = (
            await self._db.table("rifas")
            .select("*")
            .in_("status", ["ativa", "encerrada", "sorteada"])
            .order("data_sorteio", desc=False)
            .execute()
        )
        rows = result.data or []
        return [self._row_to_response(row) for row in rows]

    async def obter(self, rifa_id: str) -> RifaResponse:
        """Busca uma rifa específica."""
        result = await self._db.table("rifas").select("*").eq("id", rifa_id).execute()
        rows = result.data or []
        if not rows:
            raise RifaNaoEncontrada(rifa_id)
        return self._row_to_response(rows[0])

    async def listar_numeros(self, rifa_id: str) -> NumerosResponse:
        """Retorna a grade completa de números da rifa."""
        rifa = await self.obter(rifa_id)
        result = (
            await self._db.table("numeros_rifa")
            .select("numero,status")
            .eq("rifa_id", rifa_id)
            .order("numero")
            .execute()
        )
        numeros = [
            NumeroResponse(numero=r["numero"], status=r["status"]) for r in (result.data or [])
        ]
        disponiveis = sum(1 for n in numeros if n.status == "disponivel")
        reservados = sum(1 for n in numeros if n.status == "reservado")
        pagos = sum(1 for n in numeros if n.status == "pago")
        return NumerosResponse(
            rifa_id=rifa_id,
            total=rifa.total_numeros,
            disponiveis=disponiveis,
            reservados=reservados,
            pagos=pagos,
            numeros=numeros,
        )

    # ── Admin (CRUD de rifas) ───────────────────────────────────

    async def criar(self, payload: RifaCreate) -> RifaResponse:
        """Cria rifa e gera automaticamente a grade de números."""
        registro = payload.model_dump(mode="json")
        result = await self._db.table("rifas").insert(registro).execute()
        rifa_id = (result.data[0])["id"]

        # Gera a grade inicial de números
        numeros = [
            {"rifa_id": rifa_id, "numero": n, "status": "disponivel"}
            for n in range(payload.total_numeros)
        ]
        await self._db.table("numeros_rifa").insert(numeros).execute()

        return await self.obter(rifa_id)

    async def atualizar(self, rifa_id: str, payload: RifaUpdate) -> RifaResponse:
        """Atualiza parcialmente uma rifa."""
        updates = payload.model_dump(mode="json", exclude_unset=True)
        if not updates:
            return await self.obter(rifa_id)
        await self._db.table("rifas").update(updates).eq("id", rifa_id).execute()
        return await self.obter(rifa_id)

    async def disparar_sorteio(self, rifa_id: str) -> SorteioResponse:
        """Sorteia aleatoriamente entre os números pagos e marca o ganhador."""
        numeros_pagos = (
            await self._db.table("numeros_rifa")
            .select("numero,comprador_nome,comprador_telefone")
            .eq("rifa_id", rifa_id)
            .eq("status", "pago")
            .execute()
        ).data or []

        if not numeros_pagos:
            raise SorteioInvalido("Nenhum número pago nessa rifa")

        sorteado = random.choice(numeros_pagos)
        agora = datetime.now(UTC)

        await self._db.table("rifas").update(
            {
                "status": "sorteada",
                "numero_sorteado": sorteado["numero"],
                "ganhador_nome": sorteado.get("comprador_nome"),
                "ganhador_telefone": sorteado.get("comprador_telefone"),
                "updated_at": agora.isoformat(),
            }
        ).eq("id", rifa_id).execute()

        return SorteioResponse(
            rifa_id=rifa_id,
            numero_sorteado=sorteado["numero"],
            ganhador_nome=sorteado.get("comprador_nome"),
            ganhador_telefone=sorteado.get("comprador_telefone"),
            sorteado_em=agora,
        )

    # ── Checkout (compra de números) ────────────────────────────

    async def criar_pedido(self, payload: PedidoCreate) -> PedidoResponse:
        """Reserva números, cria pedido pendente e gera Pix."""
        rifa = await self.obter(payload.rifa_id)
        if rifa.status != "ativa":
            raise OperacaoInvalida(f"Rifa não está ativa (status={rifa.status})")

        valor_total = rifa.preco_por_numero * len(payload.numeros)
        pedido_id = str(uuid4())

        # Reservar os números atomicamente (status=reservado, pedido_id=novo)
        reservado_ate = (
            datetime.now(UTC) + timedelta(seconds=RESERVA_EXPIRACAO_SEGUNDOS)
        ).isoformat()
        dados_comprador = {
            "comprador_nome": payload.comprador_nome,
            "comprador_telefone": payload.comprador_telefone,
            "comprador_email": payload.comprador_email,
        }
        reserva_update = {
            "status": "reservado",
            "pedido_id": pedido_id,
            "reservado_ate": reservado_ate,
            **dados_comprador,
        }

        # Só reserva os que estão disponíveis (filtro explícito)
        for numero in payload.numeros:
            result = (
                await self._db.table("numeros_rifa")
                .update(reserva_update)
                .eq("rifa_id", payload.rifa_id)
                .eq("numero", numero)
                .eq("status", "disponivel")
                .execute()
            )
            if not result.data:
                # Libera reservas feitas nessa mesma chamada
                await self._liberar_reservas(pedido_id)
                raise NumeroIndisponivel(numero)

        # Cria pedido
        expires_at = datetime.now(UTC) + timedelta(seconds=PIX_EXPIRACAO_SEGUNDOS)
        registro_pedido = {
            "id": pedido_id,
            "rifa_id": payload.rifa_id,
            "total_numeros": len(payload.numeros),
            "valor_total": float(valor_total),
            "status": "pendente",
            **dados_comprador,
            "expires_at": expires_at.isoformat(),
        }
        await self._db.table("pedidos_rifa").insert(registro_pedido).execute()

        # Gera Pix (se MP estiver habilitado)
        pix_payload: PixPayload | None = None
        if self._mp.habilitado:
            mp_response = await self._mp.criar_pix(
                valor=valor_total,
                descricao=f"Rifa {rifa.titulo} — {len(payload.numeros)} número(s)",
                referencia_externa=pedido_id,
                nome_pagador=payload.comprador_nome,
                email_pagador=payload.comprador_email,
                expiracao_segundos=PIX_EXPIRACAO_SEGUNDOS,
            )
            tx = (mp_response.get("point_of_interaction") or {}).get("transaction_data") or {}
            pix_payload = PixPayload(
                payment_id=str(mp_response["id"]),
                qr_code=tx.get("qr_code", ""),
                qr_code_base64=tx.get("qr_code_base64"),
                ticket_url=tx.get("ticket_url"),
                valor_total=valor_total,
                expires_at=expires_at,
            )
            await self._db.table("pedidos_rifa").update(
                {
                    "mp_payment_id": str(mp_response["id"]),
                    "mp_qr_code": tx.get("qr_code", ""),
                    "mp_qr_code_base64": tx.get("qr_code_base64"),
                    "mp_ticket_url": tx.get("ticket_url"),
                }
            ).eq("id", pedido_id).execute()

        return PedidoResponse(
            pedido_id=pedido_id,
            rifa_id=payload.rifa_id,
            numeros=payload.numeros,
            valor_total=valor_total,
            status="pendente",
            pix=pix_payload,
        )

    async def confirmar_pagamento(self, pedido_id: str) -> PedidoResponse:
        """Marca pedido como pago e converte números reservados em pagos."""
        pedido_row = (
            await self._db.table("pedidos_rifa").select("*").eq("id", pedido_id).execute()
        ).data
        if not pedido_row:
            raise PedidoNaoEncontrado(pedido_id)

        pedido = pedido_row[0]
        if pedido["status"] == "pago":
            return self._pedido_to_response(pedido)

        agora = datetime.now(UTC)
        await self._db.table("pedidos_rifa").update(
            {"status": "pago", "paid_at": agora.isoformat(), "updated_at": agora.isoformat()}
        ).eq("id", pedido_id).execute()

        await self._db.table("numeros_rifa").update({"status": "pago", "reservado_ate": None}).eq(
            "pedido_id", pedido_id
        ).execute()

        pedido["status"] = "pago"
        pedido["paid_at"] = agora.isoformat()
        return self._pedido_to_response(pedido)

    async def liberar_expirados(self) -> int:
        """Job periódico: libera reservas e pedidos expirados. Retorna qtd liberada."""
        agora = datetime.now(UTC).isoformat()
        # Libera números reservados cujo prazo venceu
        nums = (
            await self._db.table("numeros_rifa")
            .update({"status": "disponivel", "pedido_id": None, "reservado_ate": None})
            .eq("status", "reservado")
            .lt("reservado_ate", agora)
            .execute()
        )
        liberados = len(nums.data or [])
        # Marca pedidos pendentes expirados
        await self._db.table("pedidos_rifa").update({"status": "expirado", "updated_at": agora}).eq(
            "status", "pendente"
        ).lt("expires_at", agora).execute()
        return liberados

    # ── Helpers ─────────────────────────────────────────────────

    async def _liberar_reservas(self, pedido_id: str) -> None:
        await self._db.table("numeros_rifa").update(
            {"status": "disponivel", "pedido_id": None, "reservado_ate": None}
        ).eq("pedido_id", pedido_id).execute()

    def _row_to_response(self, row: dict) -> RifaResponse:
        total = row.get("total_numeros") or 100
        # Se houver agregados pré-calculados na view, prioriza-os
        numeros_vendidos = row.get("numeros_vendidos", 0) or 0
        valor_arrecadado = Decimal(str(row.get("valor_arrecadado") or 0))
        return RifaResponse(
            id=row["id"],
            titulo=row["titulo"],
            subtitulo=row.get("subtitulo"),
            descricao=row.get("descricao"),
            imagem_url=row.get("imagem_url"),
            preco_por_numero=Decimal(str(row["preco_por_numero"])),
            total_numeros=total,
            data_sorteio=row["data_sorteio"],
            regulamento=row.get("regulamento"),
            status=row["status"],
            numero_sorteado=row.get("numero_sorteado"),
            ganhador_nome=row.get("ganhador_nome"),
            numeros_vendidos=numeros_vendidos,
            valor_arrecadado=valor_arrecadado,
            created_at=row["created_at"],
        )

    def _pedido_to_response(self, row: dict) -> PedidoResponse:
        pix: PixPayload | None = None
        if row.get("mp_payment_id"):
            pix = PixPayload(
                payment_id=str(row["mp_payment_id"]),
                qr_code=row.get("mp_qr_code") or "",
                qr_code_base64=row.get("mp_qr_code_base64"),
                ticket_url=row.get("mp_ticket_url"),
                valor_total=Decimal(str(row["valor_total"])),
                expires_at=row["expires_at"],
            )
        # numeros vem via lookup rápido
        return PedidoResponse(
            pedido_id=row["id"],
            rifa_id=row["rifa_id"],
            numeros=_fetch_numeros(self._db, row["id"]),
            valor_total=Decimal(str(row["valor_total"])),
            status=row["status"],
            pix=pix,
        )


async def _fetch_numeros(db: AsyncClient, pedido_id: str) -> list[int]:
    result = (
        await db.table("numeros_rifa")
        .select("numero")
        .eq("pedido_id", pedido_id)
        .order("numero")
        .execute()
    )
    return [r["numero"] for r in (result.data or [])]


# ── Exceções de domínio ───────────────────────────────────────


class RifaNaoEncontrada(LookupError):
    def __init__(self, rifa_id: str) -> None:
        super().__init__(f"Rifa {rifa_id} não encontrada")
        self.rifa_id = rifa_id


class PedidoNaoEncontrado(LookupError):
    def __init__(self, pedido_id: str) -> None:
        super().__init__(f"Pedido {pedido_id} não encontrado")
        self.pedido_id = pedido_id


class NumeroIndisponivel(RuntimeError):
    def __init__(self, numero: int) -> None:
        super().__init__(f"Número {numero} não está disponível")
        self.numero = numero


class OperacaoInvalida(RuntimeError):
    """Estado inconsistente (ex: rifa não ativa)."""


class SorteioInvalido(RuntimeError):
    """Sorteio sem números pagos."""
