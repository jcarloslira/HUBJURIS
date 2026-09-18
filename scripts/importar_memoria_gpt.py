"""Importa o dossiê de migração do ChatGPT para a base de conhecimento do Hub.

O escritório usava o ChatGPT antes do LexHub; o histórico de lá foi consolidado
num dossiê (preferências de redação, teses, portfólio, casos e status). Este
script ingere esse material na base semântica, ESCOPADO ao escritório — nenhum
outro tenant enxerga.

Uso:
    uv run python scripts/importar_memoria_gpt.py <arquivo.md> <escritorio_id> [--fonte slug]
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # roda de qualquer pasta

from app.config import get_settings
from app.services.conhecimento import ConhecimentoService
from app.utils.supabase import create_supabase_client

CABECALHO = """[MEMÓRIA HERDADA DO CHATGPT — consolidada em {data}]
Este material é a memória do escritório trazida da ferramenta anterior: preferências de
redação, teses recorrentes, portfólio e status dos casos. Vale como CONTEXTO e padrão de
trabalho. Onde falar de status de processo, confirme sempre no EasyJur/Hub antes de usar:
o dossiê é um resumo declarado, não a fonte oficial do andamento.

"""


async def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivo", type=Path)
    parser.add_argument("escritorio_id")
    parser.add_argument("--fonte", default="memoria-gpt")
    parser.add_argument("--titulo", default="Memória do escritório herdada do ChatGPT")
    parser.add_argument("--categoria", default="memoria-escritorio")
    parser.add_argument(
        "--diretrizes",
        type=Path,
        help="Arquivo com as regras de estilo/método a gravar em escritorios.diretrizes "
        "(vão no prompt de todo agente do escritório, não na busca).",
    )
    args = parser.parse_args()

    texto = CABECALHO.format(data=date.today().strftime("%d/%m/%Y")) + args.arquivo.read_text(
        encoding="utf-8"
    )
    settings = get_settings()
    db = await create_supabase_client(settings)
    async with httpx.AsyncClient(timeout=120) as http:
        kb = ConhecimentoService(db, http, settings)
        doc_id, chunks = await kb.ingerir_documento(
            titulo=args.titulo,
            texto=texto,
            fonte=args.fonte,
            categoria=args.categoria,
            escritorio_id=args.escritorio_id,
        )
    print(f"ok: documento {doc_id} com {chunks} trechos ({len(texto)} chars)")

    if args.diretrizes:
        regras = args.diretrizes.read_text(encoding="utf-8").strip()
        await db.table("escritorios").update({"diretrizes": regras}).eq(
            "id", args.escritorio_id
        ).execute()
        print(f"ok: diretrizes gravadas ({len(regras)} chars)")


if __name__ == "__main__":
    asyncio.run(principal())
