"""Conversão de anexos em blocos de conteúdo para a API da Anthropic.

O que o modelo processa nativamente: imagens (jpeg/png/gif/webp) e PDF. Para
documentos do Office (docx/xlsx/pptx) e arquivos de texto, extraímos o texto
com a biblioteca padrão (sem novas dependências) e o enviamos como texto.
Tipos que o modelo não lê (áudio/vídeo/binários) viram uma nota honesta, para
o agente avisar o usuário em vez de fingir que os leu.
"""

import base64
import html
import io
import re
import zipfile
from typing import Any

from app.schemas.chat import AnexoIn

# Imagens que a Messages API aceita como bloco `image`.
_IMAGENS = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Extensões de texto puro que decodificamos direto.
_TEXTO_EXT = {"txt", "csv", "md", "json", "log", "xml", "html", "yaml", "yml", "svg"}
# Teto de texto extraído por anexo (evita estourar o contexto).
_MAX_TEXTO = 20_000


def construir_blocos(texto: str, anexos: list[AnexoIn]) -> list[dict[str, Any]]:
    """Monta o conteúdo da mensagem do usuário: texto + um bloco por anexo.

    Args:
        texto: Texto digitado pelo usuário (pode ser vazio se só houver anexo).
        anexos: Lista de anexos recebidos do front.

    Returns:
        Lista de blocos de conteúdo prontos para a Messages API.
    """
    blocos: list[dict[str, Any]] = []
    if texto and texto.strip():
        blocos.append({"type": "text", "text": texto})
    for anexo in anexos:
        blocos.extend(_bloco_de(anexo))
    return blocos


def _bloco_de(anexo: AnexoIn) -> list[dict[str, Any]]:
    nome = anexo.nome
    tipo = (anexo.tipo or "").lower().strip()
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""

    try:
        dados = base64.b64decode(anexo.dados, validate=False)
    except Exception:  # noqa: BLE001 - anexo corrompido não derruba a conversa
        return [_nota(nome, "não foi possível ler o arquivo")]

    if tipo in _IMAGENS:
        return [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": tipo, "data": anexo.dados},
            }
        ]

    if tipo == "application/pdf" or ext == "pdf":
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": anexo.dados,
                },
                "title": nome,
            }
        ]

    if tipo.startswith("text/") or ext in _TEXTO_EXT:
        return [_texto(nome, _decodificar(dados))]

    extratores = {"docx": _extrair_docx, "xlsx": _extrair_xlsx, "pptx": _extrair_pptx}
    if ext in extratores:
        try:
            return [_texto(nome, extratores[ext](dados))]
        except Exception:  # noqa: BLE001 - extração best-effort
            return [_nota(nome, "não foi possível extrair o texto do documento")]

    if tipo.startswith("audio/") or tipo.startswith("video/"):
        return [
            _nota(
                nome,
                "o modelo ainda não processa áudio/vídeo diretamente — "
                "descreva o conteúdo ou envie uma transcrição",
            )
        ]

    return [_nota(nome, "tipo de arquivo não suportado para leitura direta pelo modelo")]


def _texto(nome: str, conteudo: str) -> dict[str, Any]:
    if not conteudo or not conteudo.strip():
        return _nota(nome, "não foi possível extrair texto do arquivo")
    return {"type": "text", "text": f"[Anexo: {nome}]\n{conteudo[:_MAX_TEXTO]}"}


def _nota(nome: str, motivo: str) -> dict[str, Any]:
    return {"type": "text", "text": f"[Anexo '{nome}' recebido, mas {motivo}.]"}


def _decodificar(dados: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", "ignore")


def _extrair_docx(dados: bytes) -> str:
    """Extrai o texto de um .docx lendo word/document.xml (sem dependências)."""
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(xml)


def _extrair_xlsx(dados: bytes) -> str:
    """Extrai os textos de um .xlsx a partir de xl/sharedStrings.xml."""
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        try:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
        except KeyError:
            return ""
    textos = re.findall(r"<t[^>]*>(.*?)</t>", xml, re.S)
    return html.unescape(" ".join(textos))


def _extrair_pptx(dados: bytes) -> str:
    """Extrai o texto dos slides de um .pptx."""
    partes: list[str] = []
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for nome in z.namelist():
            if nome.startswith("ppt/slides/slide") and nome.endswith(".xml"):
                xml = z.read(nome).decode("utf-8", "ignore")
                partes.extend(re.findall(r"<a:t>(.*?)</a:t>", xml, re.S))
    return html.unescape("\n".join(partes))
