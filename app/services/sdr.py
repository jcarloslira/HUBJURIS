"""Lógica de negócio do SDR: leads, qualificação, histórico, agendamentos."""

import logging
from datetime import datetime

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam
from supabase import AsyncClient

from app.agents.sdr import SDRAgent
from app.schemas.sdr import (
    AgendamentoCreate,
    AgendamentoResponse,
    EtapaFunil,
    FollowUpResponse,
    LeadDetalhe,
    LeadResponse,
    LeadUpdate,
    MensagemSDRResponse,
    MetricasFunil,
)

logger = logging.getLogger(__name__)


class SDRService:
    """Orquestra qualificação de leads e comunicação via WhatsApp."""

    def __init__(
        self,
        supabase: AsyncClient,
        anthropic: AsyncAnthropic,
    ) -> None:
        """Inicializa o serviço com clientes compartilhados.

        Args:
            supabase: Cliente Supabase para persistência.
            anthropic: Cliente Anthropic para o agente SDR.
        """
        self.db = supabase
        self.agente = SDRAgent(anthropic)

    # ── Leads ──────────────────────────────────────────────────────

    async def registrar_lead(self, telefone: str, nome: str | None = None) -> LeadResponse:
        """Cria um novo lead ou retorna o existente pelo telefone.

        Args:
            telefone: Número do WhatsApp (apenas dígitos).
            nome: Nome do contato (pushName).

        Returns:
            Lead criado ou existente.
        """
        resultado = await self.db.table("leads").select("*").eq("telefone", telefone).execute()

        if resultado.data:
            lead_data = resultado.data[0]
            if nome and not lead_data.get("nome"):
                await (
                    self.db.table("leads")
                    .update({"nome": nome, "updated_at": datetime.utcnow().isoformat()})
                    .eq("id", lead_data["id"])
                    .execute()
                )
                lead_data["nome"] = nome
            return LeadResponse.model_validate(lead_data)

        novo = await self.db.table("leads").insert({"telefone": telefone, "nome": nome}).execute()
        return LeadResponse.model_validate(novo.data[0])

    async def atualizar_lead(self, lead_id: str, dados: LeadUpdate) -> LeadResponse | None:
        """Atualiza os dados de qualificação de um lead.

        Args:
            lead_id: UUID do lead.
            dados: Campos a atualizar.

        Returns:
            Lead atualizado ou None se não encontrado.
        """
        update_data = dados.model_dump(exclude_none=True)
        if not update_data:
            return None
        update_data["updated_at"] = datetime.utcnow().isoformat()

        resultado = await self.db.table("leads").update(update_data).eq("id", lead_id).execute()
        if not resultado.data:
            return None
        return LeadResponse.model_validate(resultado.data[0])

    async def listar_leads(
        self,
        etapa: EtapaFunil | None = None,
        limite: int = 50,
    ) -> list[LeadResponse]:
        """Lista leads com filtro opcional por etapa do funil.

        Args:
            etapa: Filtrar por etapa específica do funil.
            limite: Máximo de resultados.

        Returns:
            Lista de leads.
        """
        query = self.db.table("leads").select("*").order("created_at", desc=True).limit(limite)

        if etapa:
            query = query.eq("etapa_funil", etapa)

        resultado = await query.execute()
        return [LeadResponse.model_validate(r) for r in resultado.data]

    async def obter_lead_detalhe(self, lead_id: str) -> LeadDetalhe | None:
        """Retorna o lead com histórico de mensagens e agendamentos.

        Args:
            lead_id: UUID do lead.

        Returns:
            Detalhes completos ou None.
        """
        lead_result = await self.db.table("leads").select("*").eq("id", lead_id).execute()
        if not lead_result.data:
            return None

        msgs_result = (
            await self.db.table("mensagens_sdr")
            .select("*")
            .eq("lead_id", lead_id)
            .order("created_at")
            .execute()
        )

        agend_result = (
            await self.db.table("agendamentos")
            .select("*")
            .eq("lead_id", lead_id)
            .order("data_hora", desc=True)
            .execute()
        )

        return LeadDetalhe(
            lead=LeadResponse.model_validate(lead_result.data[0]),
            mensagens=[MensagemSDRResponse.model_validate(m) for m in msgs_result.data],
            agendamentos=[AgendamentoResponse.model_validate(a) for a in agend_result.data],
        )

    # ── Mensagens ──────────────────────────────────────────────────

    async def salvar_mensagem(self, lead_id: str, direcao: str, conteudo: str) -> None:
        """Persiste uma mensagem no histórico da conversa.

        Args:
            lead_id: UUID do lead.
            direcao: "entrada" (lead→bot) ou "saida" (bot→lead).
            conteudo: Texto da mensagem.
        """
        await (
            self.db.table("mensagens_sdr")
            .insert(
                {
                    "lead_id": lead_id,
                    "direcao": direcao,
                    "conteudo": conteudo,
                }
            )
            .execute()
        )

    async def obter_historico(self, lead_id: str, limite: int = 50) -> list[MessageParam]:
        """Carrega o histórico de conversa como lista de MessageParam.

        Args:
            lead_id: UUID do lead.
            limite: Máximo de mensagens a carregar.

        Returns:
            Histórico formatado para o Anthropic SDK.
        """
        resultado = (
            await self.db.table("mensagens_sdr")
            .select("direcao, conteudo")
            .eq("lead_id", lead_id)
            .order("created_at")
            .limit(limite)
            .execute()
        )

        mensagens: list[MessageParam] = []
        for msg in resultado.data:
            role = "user" if msg["direcao"] == "entrada" else "assistant"
            mensagens.append({"role": role, "content": msg["conteudo"]})

        return mensagens

    # ── Agendamentos ───────────────────────────────────────────────

    async def agendar_consulta(self, dados: AgendamentoCreate) -> AgendamentoResponse:
        """Cria um agendamento de consulta para o lead.

        Args:
            dados: Dados do agendamento.

        Returns:
            Agendamento criado.
        """
        resultado = (
            await self.db.table("agendamentos")
            .insert(
                {
                    "lead_id": dados.lead_id,
                    "data_hora": dados.data_hora.isoformat(),
                    "tipo": dados.tipo,
                    "observacoes": dados.observacoes,
                }
            )
            .execute()
        )

        await (
            self.db.table("leads")
            .update(
                {
                    "etapa_funil": "agendado",
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            .eq("id", dados.lead_id)
            .execute()
        )

        return AgendamentoResponse.model_validate(resultado.data[0])

    async def listar_agendamentos(self, limite: int = 50) -> list[AgendamentoResponse]:
        """Lista todos os agendamentos ordenados por data.

        Args:
            limite: Máximo de resultados.

        Returns:
            Lista de agendamentos.
        """
        resultado = (
            await self.db.table("agendamentos")
            .select("*")
            .order("data_hora", desc=True)
            .limit(limite)
            .execute()
        )
        return [AgendamentoResponse.model_validate(a) for a in resultado.data]

    # ── Follow-ups ─────────────────────────────────────────────────

    async def criar_followup(
        self,
        lead_id: str,
        mensagem: str,
        data_agendada: datetime,
        tipo: str = "follow_up",
    ) -> FollowUpResponse:
        """Agenda um follow-up para envio futuro.

        Args:
            lead_id: UUID do lead.
            mensagem: Texto do follow-up.
            data_agendada: Quando enviar.
            tipo: "follow_up" ou "lembrete".

        Returns:
            Follow-up criado.
        """
        resultado = (
            await self.db.table("follow_ups")
            .insert(
                {
                    "lead_id": lead_id,
                    "tipo": tipo,
                    "mensagem": mensagem,
                    "data_agendada": data_agendada.isoformat(),
                }
            )
            .execute()
        )
        return FollowUpResponse.model_validate(resultado.data[0])

    async def obter_followups_pendentes(self) -> list[FollowUpResponse]:
        """Retorna follow-ups pendentes cuja data já passou.

        Returns:
            Lista de follow-ups prontos para envio.
        """
        agora = datetime.utcnow().isoformat()
        resultado = (
            await self.db.table("follow_ups")
            .select("*")
            .eq("enviado", False)
            .lte("data_agendada", agora)
            .order("data_agendada")
            .execute()
        )
        return [FollowUpResponse.model_validate(f) for f in resultado.data]

    async def marcar_followup_enviado(self, followup_id: str) -> None:
        """Marca um follow-up como enviado.

        Args:
            followup_id: UUID do follow-up.
        """
        await self.db.table("follow_ups").update({"enviado": True}).eq("id", followup_id).execute()

    # ── Métricas ───────────────────────────────────────────────────

    async def obter_metricas(self) -> MetricasFunil:
        """Retorna contagem de leads por etapa do funil.

        Returns:
            Métricas agregadas do funil.
        """
        resultado = await self.db.table("leads").select("etapa_funil").execute()

        contagem: dict[str, int] = {}
        for row in resultado.data:
            etapa = row["etapa_funil"]
            contagem[etapa] = contagem.get(etapa, 0) + 1

        return MetricasFunil(
            novo=contagem.get("novo", 0),
            em_qualificacao=contagem.get("em_qualificacao", 0),
            qualificado=contagem.get("qualificado", 0),
            agendado=contagem.get("agendado", 0),
            convertido=contagem.get("convertido", 0),
            descartado=contagem.get("descartado", 0),
            total=len(resultado.data),
        )

    # ── Processamento principal ────────────────────────────────────

    async def processar_mensagem(
        self, telefone: str, texto: str, push_name: str | None = None
    ) -> str:
        """Orquestra o fluxo completo: lead → histórico → agente → resposta.

        Args:
            telefone: Número do WhatsApp.
            texto: Mensagem recebida.
            push_name: Nome do contato no WhatsApp.

        Returns:
            Texto da resposta do agente.
        """
        lead = await self.registrar_lead(telefone, push_name)

        if lead.etapa_funil == "novo":
            await self.atualizar_lead(lead.id, LeadUpdate(etapa_funil="em_qualificacao"))

        await self.salvar_mensagem(lead.id, "entrada", texto)

        historico = await self.obter_historico(lead.id)

        contexto = f"[Contexto: Lead {lead.nome or 'sem nome'}, "
        contexto += f"telefone {lead.telefone}, "
        contexto += f"etapa: {lead.etapa_funil}]"
        if lead.valor_divida:
            contexto += f" [Dívida: R$ {lead.valor_divida:,.2f}]"
        if lead.qtd_credores:
            contexto += f" [Credores: {lead.qtd_credores}]"

        historico_com_contexto = list(historico)
        if len(historico_com_contexto) > 0:
            primeira = historico_com_contexto[0]
            historico_com_contexto[0] = {
                "role": primeira["role"],
                "content": f"{contexto}\n\n{primeira['content']}",
            }

        resposta = await self.agente.processar(
            mensagem="",
            historico=historico_com_contexto,
        )

        await self.salvar_mensagem(lead.id, "saida", resposta)

        return resposta
