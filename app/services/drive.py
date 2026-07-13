"""M3 (Mãos) — leitura e mapeamento do acervo do Drive.

A leitura do Drive fica atrás da abstração ``DriveConnector`` para não
acoplar o app a um provedor específico (Composio, mcp.ai, Google API direto).
O cérebro desta fase é ``mapear_acervo``: recebe a árvore de pastas de um
condomínio (Condomínio → Bloco → Unidade → documentos) e devolve uma
estrutura tipada, classificando cada documento por categoria.
"""

import re
from typing import Protocol

from pydantic import BaseModel, Field


class DriveEntry(BaseModel):
    """Um item do Drive (pasta ou arquivo)."""

    id: str
    nome: str
    is_folder: bool
    mime: str | None = None


class DriveConnector(Protocol):
    """Contrato mínimo de acesso ao Drive, independente do provedor."""

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        """Lista os itens (pastas e arquivos) diretamente dentro de uma pasta."""
        ...


class DocumentoMapeado(BaseModel):
    """Documento identificado no acervo, já classificado por categoria."""

    nome: str
    categoria: str
    drive_file_id: str
    caminho: str
    mime: str | None = None


class UnidadeMapeada(BaseModel):
    """Unidade identificada (pasta de 3º nível)."""

    identificacao: str
    drive_folder_id: str


class BlocoMapeado(BaseModel):
    """Bloco identificado (pasta de 2º nível) e suas unidades."""

    nome: str
    drive_folder_id: str
    unidades: list[UnidadeMapeada] = Field(default_factory=list)


class CondominioMapeado(BaseModel):
    """Condomínio identificado (pasta de 1º nível), sua estrutura e documentos."""

    nome: str
    drive_folder_id: str
    blocos: list[BlocoMapeado] = Field(default_factory=list)
    documentos: list[DocumentoMapeado] = Field(default_factory=list)


# Ordem importa: chaves mais específicas primeiro. Casamento por trecho do nome.
_REGRAS_CATEGORIA: tuple[tuple[str, str], ...] = (
    ("convenc", "convencao"),
    ("regiment", "regimento"),
    ("deliberac", "deliberacao"),
    ("notificac", "notificacao"),
    ("peticao", "peticao"),
    ("peticoes", "peticao"),
    ("parecer", "parecer"),
    ("contrato", "contrato"),
    ("acordo", "acordo"),
    ("ata", "ata"),
)


def _normalizar(texto: str) -> str:
    """Minúsculas sem acentos, para casar categorias de forma robusta."""
    subs = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")
    return texto.lower().translate(subs)


def inferir_categoria(nome: str) -> str:
    """Classifica um documento pela heurística do nome do arquivo.

    Args:
        nome: Nome do arquivo (ex.: "Convenção 2019.pdf").

    Returns:
        Categoria (`convencao`, `ata`, `contrato`, ...) ou `outro`.
    """
    normalizado = _normalizar(nome)
    tokens = set(re.findall(r"[a-z]+", normalizado))
    for chave, categoria in _REGRAS_CATEGORIA:
        # 'ata' só casa como palavra inteira, para não pegar 'data'/'relata'.
        if chave == "ata":
            if "ata" in tokens:
                return categoria
        elif chave in normalizado:
            return categoria
    return "outro"


async def _mapear_unidade(
    connector: DriveConnector, pasta: DriveEntry, prefixo: str
) -> tuple[UnidadeMapeada, list[DocumentoMapeado]]:
    documentos: list[DocumentoMapeado] = []
    for filho in await connector.listar_filhos(pasta.id):
        if not filho.is_folder:
            documentos.append(_documento(filho, caminho=f"{prefixo}/{pasta.nome}/{filho.nome}"))
    return UnidadeMapeada(identificacao=pasta.nome, drive_folder_id=pasta.id), documentos


async def _mapear_bloco(
    connector: DriveConnector, pasta: DriveEntry
) -> tuple[BlocoMapeado, list[DocumentoMapeado]]:
    unidades: list[UnidadeMapeada] = []
    documentos: list[DocumentoMapeado] = []
    for filho in await connector.listar_filhos(pasta.id):
        if filho.is_folder:
            unidade, docs = await _mapear_unidade(connector, filho, prefixo=pasta.nome)
            unidades.append(unidade)
            documentos.extend(docs)
        else:
            documentos.append(_documento(filho, caminho=f"{pasta.nome}/{filho.nome}"))
    bloco = BlocoMapeado(nome=pasta.nome, drive_folder_id=pasta.id, unidades=unidades)
    return bloco, documentos


async def _mapear_condominio(connector: DriveConnector, pasta: DriveEntry) -> CondominioMapeado:
    blocos: list[BlocoMapeado] = []
    documentos: list[DocumentoMapeado] = []
    for filho in await connector.listar_filhos(pasta.id):
        if filho.is_folder:
            bloco, docs = await _mapear_bloco(connector, filho)
            blocos.append(bloco)
            documentos.extend(docs)
        else:
            documentos.append(_documento(filho, caminho=filho.nome))
    return CondominioMapeado(
        nome=pasta.nome,
        drive_folder_id=pasta.id,
        blocos=blocos,
        documentos=documentos,
    )


def _documento(arquivo: DriveEntry, *, caminho: str) -> DocumentoMapeado:
    return DocumentoMapeado(
        nome=arquivo.nome,
        categoria=inferir_categoria(arquivo.nome),
        drive_file_id=arquivo.id,
        caminho=caminho,
        mime=arquivo.mime,
    )


async def mapear_acervo(connector: DriveConnector, raiz_id: str) -> list[CondominioMapeado]:
    """Percorre a pasta-raiz do acervo e mapeia condomínios → blocos → unidades.

    Cada pasta de 1º nível vira um condomínio; as de 2º nível, blocos; as de
    3º nível, unidades. Arquivos em qualquer nível viram documentos do
    condomínio, com o caminho relativo preservado e a categoria inferida.

    Args:
        connector: Acesso ao Drive (qualquer provedor).
        raiz_id: ID da pasta-raiz do acervo do escritório.

    Returns:
        Lista de condomínios mapeados.
    """
    condominios: list[CondominioMapeado] = []
    for entrada in await connector.listar_filhos(raiz_id):
        if entrada.is_folder:
            condominios.append(await _mapear_condominio(connector, entrada))
    return condominios
