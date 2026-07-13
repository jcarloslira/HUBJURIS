"""Testes do mapeamento do acervo do Drive (M3)."""

from app.services.drive import (
    DriveEntry,
    inferir_categoria,
    mapear_acervo,
)


class _FakeConnector:
    """Conector fake: uma árvore de pastas em memória (id -> filhos)."""

    def __init__(self, arvore: dict[str, list[DriveEntry]]) -> None:
        self._arvore = arvore

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        return self._arvore.get(pasta_id, [])


def _pasta(id_: str, nome: str) -> DriveEntry:
    return DriveEntry(id=id_, nome=nome, is_folder=True)


def _arquivo(id_: str, nome: str, mime: str = "application/pdf") -> DriveEntry:
    return DriveEntry(id=id_, nome=nome, is_folder=False, mime=mime)


def test_inferir_categoria() -> None:
    assert inferir_categoria("Convenção 2019.pdf") == "convencao"
    assert inferir_categoria("REGIMENTO INTERNO.docx") == "regimento"
    assert inferir_categoria("Ata Assembleia 2024.pdf") == "ata"
    assert inferir_categoria("Contrato Portaria.pdf") == "contrato"
    assert inferir_categoria("Notificação unidade 34.pdf") == "notificacao"
    assert inferir_categoria("Parecer honorários.pdf") == "parecer"
    # 'data' não pode ser classificado como 'ata'
    assert inferir_categoria("Base de Dados.xlsx") == "outro"
    assert inferir_categoria("foto_fachada.jpg") == "outro"


async def test_mapear_acervo_identifica_hierarquia() -> None:
    arvore = {
        "raiz": [_pasta("cond1", "Residencial Aurora"), _arquivo("solto", "leia-me.txt")],
        "cond1": [
            _pasta("blocoA", "Bloco A"),
            _arquivo("convA", "Convenção Aurora.pdf"),
        ],
        "blocoA": [
            _pasta("uni101", "Unidade 101"),
            _arquivo("ataA", "Ata Assembleia 2024.pdf"),
        ],
        "uni101": [_arquivo("notif", "Notificação barulho.pdf")],
    }
    connector = _FakeConnector(arvore)

    condominios = await mapear_acervo(connector, "raiz")

    assert len(condominios) == 1
    cond = condominios[0]
    assert cond.nome == "Residencial Aurora"
    assert cond.drive_folder_id == "cond1"

    # Bloco e unidade identificados pela profundidade da pasta
    assert [b.nome for b in cond.blocos] == ["Bloco A"]
    assert [u.identificacao for u in cond.blocos[0].unidades] == ["Unidade 101"]

    # Documentos de todos os níveis, com categoria e caminho relativo
    docs = {d.nome: d for d in cond.documentos}
    assert docs["Convenção Aurora.pdf"].categoria == "convencao"
    assert docs["Convenção Aurora.pdf"].caminho == "Convenção Aurora.pdf"
    assert docs["Ata Assembleia 2024.pdf"].categoria == "ata"
    assert docs["Ata Assembleia 2024.pdf"].caminho == "Bloco A/Ata Assembleia 2024.pdf"
    assert docs["Notificação barulho.pdf"].categoria == "notificacao"
    assert docs["Notificação barulho.pdf"].caminho == "Bloco A/Unidade 101/Notificação barulho.pdf"


async def test_mapear_acervo_ignora_arquivos_na_raiz() -> None:
    arvore = {"raiz": [_arquivo("x", "aleatorio.pdf")]}
    connector = _FakeConnector(arvore)

    condominios = await mapear_acervo(connector, "raiz")

    assert condominios == []
