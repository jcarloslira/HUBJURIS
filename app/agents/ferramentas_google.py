"""Ferramentas de AÇÃO nos conectores Google (Agenda, Gmail, Docs, Sheets).

São ações EXTERNAS (mexem na conta Google do escritório) — o agente deve sempre
PROPOR e pedir CONFIRMAÇÃO ao usuário antes de chamá-las (ver a instrução de
ações externas no system). Cada handler degrada com clareza se o serviço não
estiver conectado. A identidade no Composio é o ``escritorio_id``.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.composio_drive import ComposioClient, ComposioError

# Schemas expostos ao modelo (formato tool-use da Anthropic).
FERRAMENTAS_GOOGLE: list[dict[str, Any]] = [
    {
        "name": "criar_evento_agenda",
        "description": (
            "Cria um evento no Google Agenda do escritório (prazos, audiências, "
            "assembleias, reuniões). AÇÃO EXTERNA: só chame DEPOIS que o usuário "
            "confirmar os detalhes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título do evento."},
                "inicio": {
                    "type": "string",
                    "description": "Início no formato AAAA-MM-DDTHH:MM:SS (horário de Brasília).",
                },
                "duracao_minutos": {"type": "integer", "description": "Duração (padrão 60)."},
                "descricao": {"type": "string"},
                "convidados": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "E-mails dos convidados.",
                },
                "criar_link_meet": {
                    "type": "boolean",
                    "description": "Se verdadeiro, gera um link do Google Meet no evento.",
                },
            },
            "required": ["titulo", "inicio"],
        },
    },
    {
        "name": "rascunhar_email",
        "description": (
            "Cria um RASCUNHO de e-mail no Gmail do escritório (NÃO envia — o usuário "
            "revisa e envia). Use para comunicados a condôminos/síndicos."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "para": {"type": "string", "description": "E-mail do destinatário."},
                "assunto": {"type": "string"},
                "corpo": {"type": "string", "description": "Texto do e-mail."},
            },
            "required": ["para", "assunto", "corpo"],
        },
    },
    {
        "name": "criar_documento_google",
        "description": (
            "Cria um Google Docs no Drive do escritório a partir de Markdown (ex.: a "
            "petição/notificação/parecer que você redigiu). AÇÃO EXTERNA: confirme antes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "conteudo_markdown": {"type": "string"},
            },
            "required": ["titulo", "conteudo_markdown"],
        },
    },
    {
        "name": "criar_planilha_google",
        "description": (
            "Cria uma nova planilha (Google Sheets) no Drive do escritório (ex.: controle "
            "de inadimplência/cotas). AÇÃO EXTERNA: confirme antes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"titulo": {"type": "string"}},
            "required": ["titulo"],
        },
    },
]

# cada ferramenta depende de um serviço conectado
SERVICO_DA_FERRAMENTA: dict[str, str] = {
    "criar_evento_agenda": "agenda",
    "rascunhar_email": "gmail",
    "criar_documento_google": "docs",
    "criar_planilha_google": "sheets",
}

Handler = Callable[[dict[str, Any]], Awaitable[str]]


def ferramentas_google_disponiveis(
    clients: dict[str, "ComposioClient | None"],
) -> list[dict[str, Any]]:
    """Schemas das ferramentas cujos serviços estão configurados (client != None)."""
    return [
        f for f in FERRAMENTAS_GOOGLE if clients.get(SERVICO_DA_FERRAMENTA[f["name"]]) is not None
    ]


def _erro(servico: str, exc: Exception) -> str:
    msg = str(exc).lower()
    if "no connected account" in msg or "connected account" in msg:
        return (
            f"O {servico} ainda não está conectado neste escritório. Peça ao usuário para "
            f"conectar em Configurações → Conectores e tente de novo."
        )
    return f"Não consegui concluir a ação no {servico} agora ({exc})."


def montar_handlers_google(
    clients: dict[str, ComposioClient | None], escritorio_id: str
) -> dict[str, Handler]:
    """Handlers das ações Google, ligados aos clients já configurados por serviço."""

    async def _criar_evento(e: dict[str, Any]) -> str:
        cli = clients.get("agenda")
        if cli is None:
            return "O Google Agenda não está disponível/conectado."
        dur = int(e.get("duracao_minutos") or 60)
        args: dict[str, Any] = {
            "summary": str(e.get("titulo") or "Evento"),
            "start_datetime": str(e.get("inicio") or ""),
            "timezone": "America/Sao_Paulo",
            "event_duration_hour": dur // 60,
            "event_duration_minutes": dur % 60,
        }
        if e.get("descricao"):
            args["description"] = e["descricao"]
        if e.get("convidados"):
            args["attendees"] = e["convidados"]
        if e.get("criar_link_meet"):
            args["create_meeting_room"] = True
        try:
            await cli.executar_acao("GOOGLECALENDAR_CREATE_EVENT", escritorio_id, args)
        except ComposioError as exc:
            return _erro("Google Agenda", exc)
        meet = " (com link do Meet)" if e.get("criar_link_meet") else ""
        return f"Evento '{args['summary']}' criado na agenda do escritório{meet}."

    async def _rascunhar_email(e: dict[str, Any]) -> str:
        cli = clients.get("gmail")
        if cli is None:
            return "O Gmail não está disponível/conectado."
        args = {
            "recipient_email": str(e.get("para") or ""),
            "subject": str(e.get("assunto") or ""),
            "body": str(e.get("corpo") or ""),
        }
        try:
            await cli.executar_acao("GMAIL_CREATE_EMAIL_DRAFT", escritorio_id, args)
        except ComposioError as exc:
            return _erro("Gmail", exc)
        return (
            f"Rascunho de e-mail para {args['recipient_email']} criado no Gmail — revise e envie."
        )

    async def _criar_documento(e: dict[str, Any]) -> str:
        cli = clients.get("docs")
        if cli is None:
            return "O Google Docs não está disponível/conectado."
        args = {
            "title": str(e.get("titulo") or "Documento"),
            "markdown_text": str(e.get("conteudo_markdown") or ""),
        }
        try:
            await cli.executar_acao("GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN", escritorio_id, args)
        except ComposioError as exc:
            return _erro("Google Docs", exc)
        return f"Documento '{args['title']}' criado no Drive do escritório."

    async def _criar_planilha(e: dict[str, Any]) -> str:
        cli = clients.get("sheets")
        if cli is None:
            return "O Google Sheets não está disponível/conectado."
        args = {"title": str(e.get("titulo") or "Planilha")}
        try:
            await cli.executar_acao("GOOGLESHEETS_CREATE_GOOGLE_SHEET1", escritorio_id, args)
        except ComposioError as exc:
            return _erro("Google Sheets", exc)
        return f"Planilha '{args['title']}' criada no Drive do escritório."

    return {
        "criar_evento_agenda": _criar_evento,
        "rascunhar_email": _rascunhar_email,
        "criar_documento_google": _criar_documento,
        "criar_planilha_google": _criar_planilha,
    }
