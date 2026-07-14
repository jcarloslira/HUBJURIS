"""Testes do grounding dos agentes nos modelos do escritório."""

from app.services.drive import DriveEntry
from app.services.modelos import carregar_modelos, formatar_referencia


class _FakeLeitor:
    """Leitor de Drive fake: árvore de pastas + conteúdos por id."""

    def __init__(self, arvore: dict[str, list[DriveEntry]], textos: dict[str, str]) -> None:
        self._arvore = arvore
        self._textos = textos

    async def listar_filhos(self, pasta_id: str) -> list[DriveEntry]:
        return self._arvore.get(pasta_id, [])

    async def ler_texto(self, file_id: str) -> str:
        if file_id not in self._textos:
            raise RuntimeError("ilegível")
        return self._textos[file_id]


def _pasta(id_: str, nome: str) -> DriveEntry:
    return DriveEntry(id=id_, nome=nome, is_folder=True)


def _arquivo(id_: str, nome: str) -> DriveEntry:
    return DriveEntry(id=id_, nome=nome, is_folder=False, mime="application/pdf")


def _fake() -> _FakeLeitor:
    arvore = {
        "raiz": [
            _pasta("p1", "Modelo de Pareceres"),
            _pasta("p2", "Modelo de Rescisão Contratual"),
        ],
        "p1": [
            _arquivo("a1", "PARECER_SARGENTO_WOLF.docx"),
            _arquivo("a2", "PARECER_MONT_BELLO.docx"),
        ],
        "p2": [_arquivo("b1", "rescisao.docx")],
    }
    textos = {
        "a1": "Ementa: ... conteúdo do parecer 1.",
        "a2": "Ementa: ... conteúdo do parecer 2.",
        "b1": "Minuta de rescisão ...",
    }
    return _FakeLeitor(arvore, textos)


async def test_carrega_modelos_da_pasta_de_pareceres() -> None:
    modelos = await carregar_modelos(_fake(), "raiz", "pareceres", limite=5)

    assert [m.nome for m in modelos] == ["PARECER_SARGENTO_WOLF.docx", "PARECER_MONT_BELLO.docx"]
    assert modelos[0].conteudo.startswith("Ementa")


async def test_contratos_casa_rescisao_contratual() -> None:
    modelos = await carregar_modelos(_fake(), "raiz", "contratos", limite=5)

    assert [m.nome for m in modelos] == ["rescisao.docx"]


async def test_respeita_limite() -> None:
    modelos = await carregar_modelos(_fake(), "raiz", "pareceres", limite=1)

    assert len(modelos) == 1


async def test_supervisor_nao_tem_modelos() -> None:
    assert await carregar_modelos(_fake(), "raiz", "supervisor") == []


async def test_pasta_inexistente_retorna_vazio() -> None:
    fake = _FakeLeitor({"raiz": [_pasta("x", "Fotos")]}, {})

    assert await carregar_modelos(fake, "raiz", "pareceres") == []


async def test_modelo_ilegivel_e_pulado() -> None:
    arvore = {
        "raiz": [_pasta("p1", "Modelo de Pareceres")],
        "p1": [_arquivo("a1", "ok.docx"), _arquivo("a2", "quebrado.docx")],
    }
    fake = _FakeLeitor(arvore, {"a1": "conteúdo ok"})  # a2 sem texto -> erro

    modelos = await carregar_modelos(fake, "raiz", "pareceres", limite=5)

    assert [m.nome for m in modelos] == ["ok.docx"]


def test_formatar_referencia() -> None:
    from app.services.modelos import Modelo

    texto = formatar_referencia([Modelo(nome="p.docx", conteudo="corpo do parecer")])

    assert "MODELOS DO ESCRITÓRIO" in texto
    assert "MODELO 1: p.docx" in texto
    assert "corpo do parecer" in texto
    assert formatar_referencia([]) == ""
