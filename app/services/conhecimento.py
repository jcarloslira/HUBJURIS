"""Base de conhecimento (RAG): embeddings via gte-small + busca semântica.

Os embeddings são gerados pela Edge Function ``embed`` do Supabase (modelo
gte-small, 384 dims, sem custo). A busca usa a função SQL ``kb_buscar`` sobre o
índice HNSW. Documentos globais (``escritorio_id`` = None) valem para todos os
escritórios; documentos com escritório ficam isolados àquele tenant.
"""

import asyncio
from collections.abc import Iterable, Iterator

import httpx
from supabase import AsyncClient

from app.config import Settings

# gte-small aceita ~512 tokens por entrada. ~1200 chars fica com folga segura.
TAMANHO_CHUNK = 1200
SOBREPOSICAO = 150
LOTE_EMBED = 2  # entradas por chamada (gte-small no free tier tem teto de CPU baixo)
TENTATIVAS_EMBED = 4  # cold-start do gte-small pode dar 546 na 1ª; retry resolve


def dividir_em_chunks(
    texto: str, tamanho: int = TAMANHO_CHUNK, sobreposicao: int = SOBREPOSICAO
) -> list[str]:
    """Quebra o texto em pedaços coesos, respeitando parágrafos quando possível.

    Acumula parágrafos até ~``tamanho`` chars; parágrafos maiores que o limite
    são fatiados com ``sobreposicao`` de contexto entre os cortes.

    Args:
        texto: Texto completo a fragmentar.
        tamanho: Tamanho-alvo de cada chunk em caracteres.
        sobreposicao: Contexto repetido entre cortes de um parágrafo longo.

    Returns:
        Lista de chunks não vazios.
    """
    paragrafos = [p.strip() for p in texto.replace("\r\n", "\n").split("\n\n") if p.strip()]
    chunks: list[str] = []
    atual = ""
    for par in paragrafos:
        if len(par) > tamanho:
            if atual:
                chunks.append(atual)
                atual = ""
            inicio = 0
            while inicio < len(par):
                chunks.append(par[inicio : inicio + tamanho])
                inicio += tamanho - sobreposicao
            continue
        if len(atual) + len(par) + 2 <= tamanho:
            atual = f"{atual}\n\n{par}" if atual else par
        else:
            if atual:
                chunks.append(atual)
            atual = par
    if atual:
        chunks.append(atual)
    return [c.strip() for c in chunks if c.strip()]


def _lotes(itens: list[str], n: int) -> Iterator[list[str]]:
    for i in range(0, len(itens), n):
        yield itens[i : i + n]


def formatar_conhecimento(trechos: Iterable[dict]) -> str:
    """Monta o bloco de referência a anexar ao system prompt do agente."""
    linhas: list[str] = []
    for t in trechos:
        titulo = t.get("titulo") or "Fonte"
        linhas.append(f"[{titulo}]\n{t.get('conteudo', '').strip()}")
    if not linhas:
        return ""
    corpo = "\n\n---\n\n".join(linhas)
    return (
        "CONHECIMENTO RECUPERADO (trechos da base do escritório e da legislação — "
        "use-os como fundamento e cite quando pertinente; se não bastarem, diga o que "
        "falta, nunca invente):\n\n" + corpo
    )


class ConhecimentoService:
    """Ingestão e busca semântica na base de conhecimento (pgvector)."""

    def __init__(
        self, supabase: AsyncClient, http: httpx.AsyncClient, settings: Settings
    ) -> None:
        self._db = supabase
        self._http = http
        self._settings = settings

    async def _embed(self, textos: list[str]) -> list[list[float]]:
        """Gera embeddings (384-dim) para uma lista de textos via Edge Function.

        Faz retry com backoff: o cold-start do gte-small pode devolver 546
        (limite de recurso) na primeira chamada pesada enquanto o modelo carrega.
        """
        url = f"{self._settings.SUPABASE_URL}/functions/v1/embed"
        headers = {
            "Authorization": f"Bearer {self._settings.SUPABASE_ANON_KEY}",
            "Content-Type": "application/json",
        }
        ultimo_erro: Exception | None = None
        for tentativa in range(TENTATIVAS_EMBED):
            try:
                resp = await self._http.post(
                    url, json={"input": textos}, headers=headers, timeout=90
                )
                resp.raise_for_status()
                return resp.json()["embeddings"]
            except httpx.HTTPStatusError as e:
                ultimo_erro = e
                if e.response.status_code not in (546, 503, 500):
                    raise
                await asyncio.sleep(1.5 * (tentativa + 1))
        assert ultimo_erro is not None
        raise ultimo_erro

    async def buscar(
        self,
        consulta: str,
        escritorio_id: str | None = None,
        *,
        k: int = 6,
        limiar: float = 0.28,
    ) -> list[dict]:
        """Busca os trechos mais relevantes para a consulta.

        Args:
            consulta: Texto da pergunta/tarefa do usuário.
            escritorio_id: Escopo do tenant; None busca só o acervo global.
            k: Máximo de trechos retornados.
            limiar: Similaridade mínima (0–1) para o trecho entrar no resultado.

        Returns:
            Lista de trechos ``{conteudo, titulo, categoria, similaridade}``.
        """
        if not consulta.strip():
            return []
        vetor = (await self._embed([consulta[:2000]]))[0]
        res = await self._db.rpc(
            "kb_buscar",
            {"query_embedding": vetor, "p_escritorio_id": escritorio_id, "match_count": k},
        ).execute()
        linhas = res.data or []
        return [r for r in linhas if (r.get("similaridade") or 0) >= limiar]

    async def ingerir_documento(
        self,
        *,
        titulo: str,
        texto: str,
        fonte: str,
        categoria: str,
        escritorio_id: str | None = None,
    ) -> tuple[str, int]:
        """Ingere um documento: fragmenta, gera embeddings e persiste.

        Idempotente por (``fonte``, escopo): reingerir substitui a versão anterior.

        Returns:
            (id do documento, quantidade de chunks).
        """
        alvo = self._db.table("kb_documentos").delete().eq("fonte", fonte)
        alvo = alvo.is_("escritorio_id", None) if escritorio_id is None else alvo.eq(
            "escritorio_id", escritorio_id
        )
        await alvo.execute()

        doc = (
            await self._db.table("kb_documentos")
            .insert(
                {
                    "titulo": titulo,
                    "fonte": fonte,
                    "categoria": categoria,
                    "escritorio_id": escritorio_id,
                }
            )
            .execute()
        )
        doc_id = str(doc.data[0]["id"])

        chunks = dividir_em_chunks(texto)
        ordem = 0
        for lote in _lotes(chunks, LOTE_EMBED):
            vetores = await self._embed(lote)
            linhas = [
                {
                    "documento_id": doc_id,
                    "escritorio_id": escritorio_id,
                    "ordem": ordem + i,
                    "conteudo": conteudo,
                    "embedding": vetor,
                }
                for i, (conteudo, vetor) in enumerate(zip(lote, vetores, strict=True))
            ]
            await self._db.table("kb_chunks").insert(linhas).execute()
            ordem += len(lote)

        await self._db.table("kb_documentos").update({"total_chunks": len(chunks)}).eq(
            "id", doc_id
        ).execute()
        return doc_id, len(chunks)
