"""Testes das funções puras da base de conhecimento (chunking e formatação)."""

from app.services.conhecimento import (
    TAMANHO_CHUNK,
    dividir_em_chunks,
    formatar_conhecimento,
)


def test_dividir_em_chunks_agrupa_paragrafos_curtos() -> None:
    texto = "Primeiro parágrafo.\n\nSegundo parágrafo.\n\nTerceiro."
    chunks = dividir_em_chunks(texto)
    # Parágrafos curtos cabem todos num único chunk.
    assert len(chunks) == 1
    assert "Primeiro" in chunks[0] and "Terceiro" in chunks[0]


def test_dividir_em_chunks_fatia_paragrafo_gigante() -> None:
    gigante = "palavra " * 1000  # ~8000 chars, muito acima do limite
    chunks = dividir_em_chunks(gigante)
    assert len(chunks) > 1
    assert all(len(c) <= TAMANHO_CHUNK for c in chunks)


def test_dividir_em_chunks_ignora_vazios() -> None:
    assert dividir_em_chunks("") == []
    assert dividir_em_chunks("\n\n   \n\n") == []


def test_formatar_conhecimento_vazio_retorna_string_vazia() -> None:
    assert formatar_conhecimento([]) == ""


def test_formatar_conhecimento_monta_bloco_com_titulos() -> None:
    trechos = [
        {"titulo": "CPC", "conteudo": "Art. 1º ...", "categoria": "lei"},
        {"titulo": "Protocolo STJ", "conteudo": "Admissibilidade ...", "categoria": "protocolo"},
    ]
    bloco = formatar_conhecimento(trechos)
    assert "CONHECIMENTO RECUPERADO" in bloco
    assert "[CPC]" in bloco and "[Protocolo STJ]" in bloco
    assert "nunca invente" in bloco
