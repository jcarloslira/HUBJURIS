"""Grounding dos agentes nos modelos do escritório (M4).

Cada especialista se abastece da pasta de modelos da sua categoria no acervo do
escritório e produz **no estilo do escritório** — é isto que entrega a
"assertividade" e o "seguir o padrão anterior" pedidos pelo Dr. Wilker.
"""

from typing import Protocol

from pydantic import BaseModel

from app.services.drive import DriveEntry


class LeitorDrive(Protocol):
    """Conector capaz de listar pastas e ler o conteúdo de arquivos."""

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        """Lista os itens diretos de uma pasta."""
        ...

    async def ler_texto(self, file_id: str) -> str:
        """Lê o conteúdo textual de um arquivo."""
        ...


class Modelo(BaseModel):
    """Um documento-modelo do escritório, usado como referência de estilo."""

    nome: str
    conteudo: str


# slug do agente -> palavras (sem acento) que identificam a pasta de modelos
_SLUG_PALAVRAS: dict[str, tuple[str, ...]] = {
    "pareceres": ("parecer",),
    "contratos": ("contrato", "rescis"),
    "peticoes": ("peticao", "peticoes"),
    "notificacoes": ("notificac",),
    "juridico-geral": ("convenc", "regiment"),
    "consulta-historica": ("ata", "deliberac"),
}


def _norm(texto: str) -> str:
    subs = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")
    return texto.lower().translate(subs)


def _pasta_do_agente(itens: list[DriveEntry], agente_slug: str) -> DriveEntry | None:
    palavras = _SLUG_PALAVRAS.get(agente_slug)
    if not palavras:
        return None
    for item in itens:
        if item.is_folder and any(p in _norm(item.nome) for p in palavras):
            return item
    return None


async def carregar_modelos(
    connector: LeitorDrive,
    raiz_id: str,
    agente_slug: str,
    *,
    limite: int = 3,
) -> list[Modelo]:
    """Carrega até ``limite`` modelos do escritório para o agente se basear.

    Args:
        connector: Acesso de leitura ao Drive do escritório.
        raiz_id: Pasta-raiz do acervo do escritório.
        agente_slug: Especialista que vai usar os modelos.
        limite: Máximo de modelos a carregar (cada leitura tem custo).

    Returns:
        Modelos com nome e conteúdo; lista vazia se não houver pasta/arquivos.
    """
    itens_raiz = await connector.listar_filhos(raiz_id)
    pasta = _pasta_do_agente(itens_raiz, agente_slug)
    if pasta is None:
        return []
    arquivos = [f for f in await connector.listar_filhos(pasta.id) if not f.is_folder]
    modelos: list[Modelo] = []
    for arquivo in arquivos[:limite]:
        try:
            texto = await connector.ler_texto(arquivo.id)
        except Exception:  # noqa: BLE001 - um modelo ilegível não derruba os demais
            continue
        modelos.append(Modelo(nome=arquivo.nome, conteudo=texto))
    return modelos


def formatar_referencia(modelos: list[Modelo]) -> str:
    """Formata os modelos como bloco de referência para o prompt do agente."""
    if not modelos:
        return ""
    partes = [
        "MODELOS DO ESCRITÓRIO — siga rigorosamente este padrão de redação, "
        "estrutura e linguagem ao produzir sua resposta:",
    ]
    for i, modelo in enumerate(modelos, 1):
        partes.append(f"\n--- MODELO {i}: {modelo.nome} ---\n{modelo.conteudo.strip()}")
    return "\n".join(partes)
