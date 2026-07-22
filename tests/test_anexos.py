"""Testes da conversão de anexos em blocos de conteúdo + fiação no chat."""

import base64
import io
import zipfile
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

from app.schemas.chat import AnexoIn, ChatRequest, MensagemChat
from app.services.anexos import construir_blocos
from app.services.chat import gerar_resposta_stream


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


def _docx(texto: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "word/document.xml",
            f"<w:document><w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>",
        )
    return _b64(buf.getvalue())


def _xlsx(texto: str) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst><si><t>{texto}</t></si></sst>")
    return _b64(buf.getvalue())


# ── construir_blocos ────────────────────────────────────────────


def test_texto_vem_primeiro_e_imagem_vira_bloco_image() -> None:
    anexo = AnexoIn(nome="foto.png", tipo="image/png", dados=_b64(b"\x89PNG..."))
    blocos = construir_blocos("olha isso", [anexo])

    assert blocos[0] == {"type": "text", "text": "olha isso"}
    assert blocos[1]["type"] == "image"
    assert blocos[1]["source"]["media_type"] == "image/png"


def test_pdf_vira_document_por_extensao() -> None:
    anexo = AnexoIn(nome="peticao.pdf", tipo="", dados=_b64(b"%PDF-1.4"))
    blocos = construir_blocos("", [anexo])

    assert blocos[0]["type"] == "document"
    assert blocos[0]["source"]["media_type"] == "application/pdf"
    assert blocos[0]["title"] == "peticao.pdf"


def test_txt_vira_texto_com_conteudo() -> None:
    anexo = AnexoIn(nome="notas.txt", tipo="text/plain", dados=_b64("Cláusula 5ª".encode()))
    blocos = construir_blocos("", [anexo])

    assert blocos[0]["type"] == "text"
    assert "Cláusula 5ª" in blocos[0]["text"]


def test_docx_extrai_texto() -> None:
    anexo = AnexoIn(nome="contrato.docx", tipo="", dados=_docx("Rescisão contratual amigável"))
    blocos = construir_blocos("", [anexo])

    assert blocos[0]["type"] == "text"
    assert "Rescisão contratual amigável" in blocos[0]["text"]


def test_xlsx_extrai_textos() -> None:
    anexo = AnexoIn(nome="planilha.xlsx", tipo="", dados=_xlsx("Inadimplentes"))
    blocos = construir_blocos("", [anexo])

    assert "Inadimplentes" in blocos[0]["text"]


def test_audio_vira_nota_honesta() -> None:
    anexo = AnexoIn(nome="reuniao.mp3", tipo="audio/mpeg", dados=_b64(b"ID3..."))
    blocos = construir_blocos("", [anexo])

    assert blocos[0]["type"] == "text"
    assert "áudio" in blocos[0]["text"].lower()


# ── Fiação no chat (a última mensagem vira blocos) ──────────────


class _FakeStream:
    def __init__(self, partes: list[str]) -> None:
        self._partes = partes
        self.text_stream: AsyncIterator[str] | None = None

    async def __aenter__(self) -> "_FakeStream":
        async def _gen() -> AsyncIterator[str]:
            for parte in self._partes:
                yield parte

        self.text_stream = _gen()
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


async def test_chat_injeta_anexos_na_ultima_mensagem() -> None:
    fake = MagicMock()
    fake.messages.stream = MagicMock(return_value=_FakeStream(["ok"]))
    payload = ChatRequest(
        agente="pareceres",  # especialista: sem roteamento
        mensagens=[MensagemChat(role="user", content="analise o anexo")],
        anexos=[AnexoIn(nome="doc.pdf", tipo="application/pdf", dados=_b64(b"%PDF"))],
    )

    trechos = [t async for t in gerar_resposta_stream(payload, fake)]

    assert trechos == ["ok"]
    conteudo = fake.messages.stream.call_args.kwargs["messages"][-1]["content"]
    assert isinstance(conteudo, list)
    tipos = [b["type"] for b in conteudo]
    assert "text" in tipos and "document" in tipos
