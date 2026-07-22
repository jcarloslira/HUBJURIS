"""Router de exportação de documentos — o "Gabinete Designer".

Recebe o conteúdo (Markdown) produzido por um agente e devolve o arquivo pronto
para download em Word, PDF ou Excel. Requer login (o conteúdo é do escritório).
"""

import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.dependencies import get_current_user
from app.schemas.auth import AuthUser
from app.schemas.documentos import ExportarPayload
from app.services.documentos import gerar_docx, gerar_pdf, gerar_xlsx

router = APIRouter(prefix="/api/documentos", tags=["documentos"])

_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _slug(nome: str) -> str:
    """Nome de arquivo seguro (ASCII, sem espaços)."""
    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    limpo = re.sub(r"[^\w\s-]", "", ascii_).strip().lower()
    limpo = re.sub(r"[\s_-]+", "-", limpo)
    return limpo[:60].strip("-") or "documento"


@router.post("/exportar")
async def exportar(
    payload: ExportarPayload,
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> Response:
    """Gera o documento no formato pedido e devolve para download."""
    if payload.formato == "docx":
        dados = gerar_docx(payload.titulo, payload.conteudo, payload.escritorio)
    elif payload.formato == "pdf":
        dados = gerar_pdf(payload.titulo, payload.conteudo, payload.escritorio)
    else:
        dados = gerar_xlsx(payload.titulo, payload.conteudo)

    nome = f"{_slug(payload.titulo)}.{payload.formato}"
    return Response(
        content=dados,
        media_type=_MEDIA[payload.formato],
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
