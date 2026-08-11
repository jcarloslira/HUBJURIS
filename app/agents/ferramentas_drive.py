"""Ferramentas que tornam os agentes EXPERTS no Google Drive do escritório.

Leitura (buscar, listar, ler) é autônoma — o agente vasculha o acervo, mesmo
desorganizado, para achar convenções, modelos e peças anteriores. Escrita
(criar pasta, mover, salvar) MEXE no Drive do escritório e deve ser sempre
proposta-e-confirmada. A identidade no Composio é o ``escritorio_id``.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.services.composio_drive import ComposioClient, ComposioError

_FOLDER_MIME = "application/vnd.google-apps.folder"
_DOC_MIME = "application/vnd.google-apps.document"
_LIMITE_LEITURA = 6000  # chars devolvidos ao ler um documento (evita estourar contexto)

Handler = Callable[[dict[str, Any]], Awaitable[str]]

# Schemas expostos ao modelo (formato tool-use da Anthropic).
FERRAMENTAS_DRIVE: list[dict[str, Any]] = [
    {
        "name": "buscar_no_drive",
        "description": (
            "Busca arquivos/pastas no Google Drive do escritório por nome ou conteúdo "
            "(ex.: 'notificação Bloco B', 'convenção Solar das Flores'). Use para achar "
            "modelos, convenções e peças anteriores. LEITURA: pode usar livremente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "termo": {"type": "string", "description": "Texto a procurar no nome/conteúdo."}
            },
            "required": ["termo"],
        },
    },
    {
        "name": "listar_pasta_drive",
        "description": (
            "Lista as pastas e arquivos dentro de uma pasta do Drive do escritório. "
            "Sem 'pasta_id', lista a raiz. Use para navegar o acervo. LEITURA: livre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pasta_id": {
                    "type": "string",
                    "description": "ID da pasta (omita ou 'root' para a raiz).",
                }
            },
        },
    },
    {
        "name": "ler_documento_drive",
        "description": (
            "Lê o conteúdo de texto de um arquivo do Drive pelo seu ID (obtido em "
            "buscar_no_drive/listar_pasta_drive). Use para se basear no documento real. "
            "LEITURA: livre."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"file_id": {"type": "string", "description": "ID do arquivo."}},
            "required": ["file_id"],
        },
    },
    {
        "name": "criar_pasta_drive",
        "description": (
            "Cria uma pasta no Drive do escritório (ex.: organizar por condomínio). "
            "AÇÃO EXTERNA: proponha e confirme com o usuário ANTES de chamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome da nova pasta."},
                "pasta_pai_id": {
                    "type": "string",
                    "description": "ID da pasta onde criar (omita para a raiz).",
                },
            },
            "required": ["nome"],
        },
    },
    {
        "name": "mover_arquivo_drive",
        "description": (
            "Move um arquivo/pasta para outra pasta no Drive (organizar o acervo). "
            "AÇÃO EXTERNA: proponha e confirme ANTES de chamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "ID do item a mover."},
                "para_pasta_id": {"type": "string", "description": "ID da pasta destino."},
                "de_pasta_id": {
                    "type": "string",
                    "description": "ID da pasta de origem a remover (opcional).",
                },
            },
            "required": ["file_id", "para_pasta_id"],
        },
    },
    {
        "name": "salvar_no_drive",
        "description": (
            "Salva um texto (ex.: a peça que você redigiu) como documento no Drive do "
            "escritório. AÇÃO EXTERNA: proponha e confirme ANTES de chamar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nome_arquivo": {"type": "string", "description": "Nome do documento."},
                "conteudo": {"type": "string", "description": "Texto/markdown a salvar."},
                "pasta_id": {
                    "type": "string",
                    "description": "ID da pasta destino (omita para a raiz).",
                },
            },
            "required": ["nome_arquivo", "conteudo"],
        },
    },
]

NOMES_DRIVE = {f["name"] for f in FERRAMENTAS_DRIVE}


def _erro_drive(exc: Exception) -> str:
    msg = str(exc).lower()
    if "connected account" in msg or "no connected" in msg:
        return (
            "O Google Drive ainda não está conectado neste escritório. Peça ao usuário "
            "para conectar em Configurações → Conectores."
        )
    return f"Não consegui concluir a operação no Drive agora ({exc})."


def montar_handlers_drive(composio: ComposioClient, escritorio_id: str) -> dict[str, Handler]:
    """Handlers das ferramentas de Drive, ligados ao escritório (user_id)."""

    async def _buscar(e: dict[str, Any]) -> str:
        termo = str(e.get("termo") or "").strip().replace("'", "\\'")
        if not termo:
            return "Informe o que buscar."
        try:
            data = await composio.executar_acao(
                "GOOGLEDRIVE_LIST_FILES",
                escritorio_id,
                {
                    "q": f"(name contains '{termo}' or fullText contains '{termo}') "
                    "and trashed = false",
                    "pageSize": 30,
                    "fields": "files(id,name,mimeType)",
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                },
            )
        except ComposioError as exc:
            return _erro_drive(exc)
        arquivos = data.get("files", [])
        if not arquivos:
            return f"Nada encontrado no Drive para '{termo}'."
        linhas = [
            f"- {a.get('name', '?')} "
            f"({'pasta' if a.get('mimeType') == _FOLDER_MIME else 'arquivo'}) "
            f"[id: {a.get('id')}]"
            for a in arquivos
        ]
        return f"Encontrei no Drive ({len(arquivos)}):\n" + "\n".join(linhas)

    async def _listar(e: dict[str, Any]) -> str:
        pasta = str(e.get("pasta_id") or "root")
        try:
            itens = await composio.listar_filhos(escritorio_id, pasta)
        except ComposioError as exc:
            return _erro_drive(exc)
        if not itens:
            return "Pasta vazia (ou sem itens acessíveis)."
        linhas = [
            f"- {it.nome} ({'pasta' if it.is_folder else 'arquivo'}) [id: {it.id}]" for it in itens
        ]
        return "Conteúdo da pasta:\n" + "\n".join(linhas)

    async def _ler(e: dict[str, Any]) -> str:
        file_id = str(e.get("file_id") or "").strip()
        if not file_id:
            return "Informe o id do arquivo."
        try:
            texto = await composio.ler_texto(escritorio_id, file_id)
        except ComposioError as exc:
            return _erro_drive(exc)
        if len(texto) > _LIMITE_LEITURA:
            texto = texto[:_LIMITE_LEITURA] + "\n[...documento truncado...]"
        return texto or "(documento sem texto extraível)"

    async def _criar_pasta(e: dict[str, Any]) -> str:
        nome = str(e.get("nome") or "").strip()
        if not nome:
            return "Informe o nome da pasta."
        args: dict[str, Any] = {"folder_name": nome}
        if e.get("pasta_pai_id"):
            args["parent_id"] = str(e["pasta_pai_id"])
        try:
            data = await composio.executar_acao("GOOGLEDRIVE_CREATE_FOLDER", escritorio_id, args)
        except ComposioError as exc:
            return _erro_drive(exc)
        return f"Pasta '{nome}' criada no Drive (id {data.get('id', '?')})."

    async def _mover(e: dict[str, Any]) -> str:
        file_id = str(e.get("file_id") or "").strip()
        destino = str(e.get("para_pasta_id") or "").strip()
        if not file_id or not destino:
            return "Informe o id do arquivo e a pasta destino."
        args: dict[str, Any] = {"file_id": file_id, "add_parents": destino}
        if e.get("de_pasta_id"):
            args["remove_parents"] = str(e["de_pasta_id"])
        try:
            await composio.executar_acao("GOOGLEDRIVE_MOVE_FILE", escritorio_id, args)
        except ComposioError as exc:
            return _erro_drive(exc)
        return "Arquivo movido no Drive para a pasta destino."

    async def _salvar(e: dict[str, Any]) -> str:
        nome = str(e.get("nome_arquivo") or "").strip()
        conteudo = str(e.get("conteudo") or "")
        if not nome or not conteudo.strip():
            return "Informe o nome do arquivo e o conteúdo a salvar."
        args: dict[str, Any] = {
            "file_name": nome,
            "mime_type": _DOC_MIME,
            "text_content": conteudo,
        }
        if e.get("pasta_id"):
            args["parent_id"] = str(e["pasta_id"])
        try:
            data = await composio.executar_acao(
                "GOOGLEDRIVE_CREATE_FILE_FROM_TEXT", escritorio_id, args
            )
        except ComposioError as exc:
            return _erro_drive(exc)
        return f"Documento '{nome}' salvo no Drive do escritório (id {data.get('id', '?')})."

    return {
        "buscar_no_drive": _buscar,
        "listar_pasta_drive": _listar,
        "ler_documento_drive": _ler,
        "criar_pasta_drive": _criar_pasta,
        "mover_arquivo_drive": _mover,
        "salvar_no_drive": _salvar,
    }
