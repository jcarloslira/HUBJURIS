"""Backend standalone da Rifa Naeliton Prêmios.

Servidor próprio e independente: serve o site estático, gera Pix reais via
Mercado Pago (token no .env), sorteia números (1–58.000), permite ao cliente
consultar seus números e dá um painel admin para o Naeliton gerir tudo.
Sem Supabase, sem Emergent — persistência local em SQLite.

Rodar:  uv run python nosso-site/server.py
"""

from __future__ import annotations

import os
import random
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
# DB_PATH pode ser sobrescrito pelo ambiente (ex.: disco persistente /data no Render)
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE / "pedidos.db")))

# ── Regras da rifa ────────────────────────────────────────────────────
PRECO_TITULO = Decimal("0.25")
TOTAL_NUMEROS = 58_000          # números disponíveis (00001–58000)
VENDIDOS_FICTICIOS = int(TOTAL_NUMEROS * 0.06)  # 6% de prova social (3.480)
PIX_EXPIRA_SEG = 1800           # 30 min
MP_API = "https://api.mercadopago.com/v1/payments"


# ── Carregamento do .env (sem dependências externas) ──────────────────
def _load_env() -> None:
    for candidate in (BASE / ".env", BASE.parent / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


_load_env()
MP_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "naeliton-admin")


# ── Banco (SQLite) ────────────────────────────────────────────────────
def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _init_db() -> None:
    with _db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pedidos (
                id TEXT PRIMARY KEY,
                mp_payment_id TEXT,
                qtd INTEGER NOT NULL,
                valor REAL NOT NULL,
                nome TEXT NOT NULL,
                cpf TEXT,
                telefone TEXT,
                email TEXT,
                status TEXT NOT NULL DEFAULT 'pendente',
                qr_code TEXT,
                created_at TEXT NOT NULL,
                paid_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS numeros (
                numero INTEGER PRIMARY KEY,
                pedido_id TEXT NOT NULL,
                cpf TEXT,
                nome TEXT,
                criado_em TEXT NOT NULL
            )
            """
        )


def _fmt_num(n: int) -> str:
    """Formata o número da cota com 5 dígitos (ex.: 00042)."""
    return str(n).zfill(5)


def _atribuir_numeros(con: sqlite3.Connection, pedido: sqlite3.Row) -> list[int]:
    """Sorteia `qtd` números livres e vincula ao pedido (idempotente)."""
    ja = [r["numero"] for r in con.execute(
        "SELECT numero FROM numeros WHERE pedido_id=?", (pedido["id"],)
    ).fetchall()]
    if ja:
        return sorted(ja)

    usados = {r["numero"] for r in con.execute("SELECT numero FROM numeros").fetchall()}
    disponiveis = TOTAL_NUMEROS - len(usados)
    qtd = min(pedido["qtd"], disponiveis)
    escolhidos: list[int] = []
    # Amostragem por rejeição — eficiente enquanto a rifa não está quase cheia
    while len(escolhidos) < qtd:
        n = random.randint(1, TOTAL_NUMEROS)
        if n not in usados:
            usados.add(n)
            escolhidos.append(n)
    agora = datetime.now(UTC).isoformat()
    con.executemany(
        "INSERT OR IGNORE INTO numeros (numero, pedido_id, cpf, nome, criado_em) VALUES (?,?,?,?,?)",
        [(n, pedido["id"], pedido["cpf"], pedido["nome"], agora) for n in escolhidos],
    )
    return sorted(escolhidos)


def _vendidos_reais(con: sqlite3.Connection) -> int:
    row = con.execute(
        "SELECT COALESCE(SUM(qtd),0) AS s FROM pedidos WHERE status='pago'"
    ).fetchone()
    return int(row["s"] or 0)


# ── Schemas ───────────────────────────────────────────────────────────
class PixIn(BaseModel):
    qtd: int = Field(ge=1, le=TOTAL_NUMEROS)
    nome: str = Field(min_length=2, max_length=120)
    cpf: str = Field(min_length=11, max_length=11)
    telefone: str = Field(min_length=10, max_length=11)
    email: str | None = None


class LoginIn(BaseModel):
    cpf: str = Field(min_length=11, max_length=11)
    telefone: str = Field(min_length=10, max_length=11)


# ── App / lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    app.state.http = httpx.AsyncClient(timeout=20.0)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Naeliton Prêmios · Rifa JBL Boombox 4", lifespan=lifespan)


# ── API pública ───────────────────────────────────────────────────────
@app.get("/api/health")
async def health() -> dict:
    """Confere se o token do Mercado Pago autentica (sem efeito colateral)."""
    if not MP_TOKEN:
        return {"mp_token": False, "mp_ok": False, "motivo": "token ausente no .env"}
    try:
        r = await app.state.http.get(
            "https://api.mercadopago.com/users/me",
            headers={"Authorization": f"Bearer {MP_TOKEN}"},
        )
        ok = r.status_code == 200
        data = r.json() if ok else {}
        return {
            "mp_token": True,
            "mp_ok": ok,
            "ambiente": "producao" if MP_TOKEN.startswith("APP_USR") else "teste",
            "conta": data.get("nickname"),
            "site_id": data.get("site_id"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"mp_token": True, "mp_ok": False, "erro": str(exc)}


@app.get("/api/stats")
async def stats() -> dict:
    """Progresso da campanha (inclui a base fictícia de prova social)."""
    with _db() as con:
        reais = _vendidos_reais(con)
    vendidos = VENDIDOS_FICTICIOS + reais
    pct = round(vendidos / TOTAL_NUMEROS * 100, 1)
    return {
        "total": TOTAL_NUMEROS,
        "vendidos": vendidos,
        "vendidos_reais": reais,
        "disponiveis": TOTAL_NUMEROS - vendidos,
        "pct": pct,
    }


@app.post("/api/pix")
async def criar_pix(body: PixIn) -> dict:
    """Cria o pedido e gera um Pix real no Mercado Pago."""
    if not MP_TOKEN:
        raise HTTPException(status_code=503, detail="Mercado Pago não configurado no servidor.")

    valor = (PRECO_TITULO * body.qtd).quantize(Decimal("0.01"))
    pedido_id = str(uuid.uuid4())
    agora = datetime.now(UTC)

    payload = {
        "transaction_amount": float(valor),
        "description": f"Rifa JBL Boombox 4 — {body.qtd} numero(s)",
        "payment_method_id": "pix",
        "external_reference": pedido_id,
        "date_of_expiration": (agora + timedelta(seconds=PIX_EXPIRA_SEG))
        .isoformat(timespec="milliseconds"),
        "payer": {
            "first_name": body.nome.split(" ", 1)[0],
            "last_name": body.nome.split(" ", 1)[-1] if " " in body.nome else "Participante",
            "identification": {"type": "CPF", "number": body.cpf},
            **({"email": body.email} if body.email else {}),
        },
    }
    headers = {
        "Authorization": f"Bearer {MP_TOKEN}",
        "X-Idempotency-Key": pedido_id,
        "Content-Type": "application/json",
    }

    r = await app.state.http.post(MP_API, json=payload, headers=headers)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Mercado Pago: {r.text[:300]}")

    mp = r.json()
    tx = (mp.get("point_of_interaction") or {}).get("transaction_data") or {}
    mp_id = str(mp.get("id"))

    with _db() as con:
        con.execute(
            """INSERT INTO pedidos
               (id, mp_payment_id, qtd, valor, nome, cpf, telefone, email,
                status, qr_code, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pedido_id, mp_id, body.qtd, float(valor), body.nome, body.cpf,
                body.telefone, body.email, "pendente", tx.get("qr_code", ""),
                agora.isoformat(),
            ),
        )

    return {
        "pedido_id": pedido_id,
        "payment_id": mp_id,
        "valor": float(valor),
        "qr_code": tx.get("qr_code", ""),
        "qr_code_base64": tx.get("qr_code_base64"),
        "ticket_url": tx.get("ticket_url"),
    }


@app.get("/api/pix/{payment_id}")
async def status_pix(payment_id: str) -> dict:
    """Consulta o status no MP; ao aprovar, marca pago e sorteia os números."""
    if not MP_TOKEN:
        raise HTTPException(status_code=503, detail="Mercado Pago não configurado.")

    r = await app.state.http.get(
        f"{MP_API}/{payment_id}",
        headers={"Authorization": f"Bearer {MP_TOKEN}"},
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado.")

    status = r.json().get("status", "pending")
    numeros: list[int] = []
    if status == "approved":
        with _db() as con:
            ped = con.execute(
                "SELECT * FROM pedidos WHERE mp_payment_id=?", (payment_id,)
            ).fetchone()
            if ped:
                if ped["status"] != "pago":
                    con.execute(
                        "UPDATE pedidos SET status='pago', paid_at=? WHERE id=?",
                        (datetime.now(UTC).isoformat(), ped["id"]),
                    )
                numeros = _atribuir_numeros(con, ped)
    return {
        "payment_id": payment_id,
        "status": status,
        "numeros": [_fmt_num(n) for n in numeros],
    }


@app.post("/api/meus-numeros")
async def meus_numeros(body: LoginIn) -> dict:
    """Login simples do cliente por CPF + telefone → mostra seus números."""
    cpf = body.cpf.strip()
    tel = body.telefone.strip()
    with _db() as con:
        peds = con.execute(
            """SELECT * FROM pedidos
               WHERE cpf=? AND telefone=? AND status='pago'
               ORDER BY paid_at DESC""",
            (cpf, tel),
        ).fetchall()
        if not peds:
            # Pode existir cadastro mas sem pagamento confirmado
            existe = con.execute(
                "SELECT 1 FROM pedidos WHERE cpf=? AND telefone=? LIMIT 1", (cpf, tel)
            ).fetchone()
            if not existe:
                raise HTTPException(status_code=404, detail="Nenhum cadastro encontrado com esse CPF e telefone.")
            return {"nome": None, "total": 0, "pedidos": [], "numeros": []}

        nome = peds[0]["nome"]
        pedidos_out = []
        todos: list[int] = []
        for p in peds:
            nums = sorted(
                r["numero"] for r in con.execute(
                    "SELECT numero FROM numeros WHERE pedido_id=?", (p["id"],)
                ).fetchall()
            )
            todos.extend(nums)
            pedidos_out.append({
                "data": p["paid_at"],
                "qtd": p["qtd"],
                "valor": p["valor"],
                "numeros": [_fmt_num(n) for n in nums],
            })
    return {
        "nome": nome,
        "total": len(todos),
        "pedidos": pedidos_out,
        "numeros": [_fmt_num(n) for n in sorted(todos)],
    }


@app.get("/api/ranking")
async def ranking() -> list[dict]:
    """Top compradores por total de números pagos."""
    with _db() as con:
        rows = con.execute(
            """SELECT nome, SUM(qtd) AS titulos
               FROM pedidos WHERE status='pago'
               GROUP BY nome ORDER BY titulos DESC LIMIT 10"""
        ).fetchall()
    return [{"nome": r["nome"], "titulos": r["titulos"]} for r in rows]


# ── API admin (protegida por token) ───────────────────────────────────
def _check_admin(token: str | None) -> None:
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token de admin inválido.")


@app.get("/api/admin/dados")
async def admin_dados(x_admin_token: str | None = Header(default=None)) -> dict:
    """Todos os pedidos + resumo para o painel do Naeliton."""
    _check_admin(x_admin_token)
    with _db() as con:
        peds = con.execute("SELECT * FROM pedidos ORDER BY created_at DESC").fetchall()
        reais = _vendidos_reais(con)
        arrecadado = con.execute(
            "SELECT COALESCE(SUM(valor),0) AS v FROM pedidos WHERE status='pago'"
        ).fetchone()["v"]
        pagos = con.execute("SELECT COUNT(*) c FROM pedidos WHERE status='pago'").fetchone()["c"]
        pendentes = con.execute("SELECT COUNT(*) c FROM pedidos WHERE status='pendente'").fetchone()["c"]

        pedidos_out = []
        for p in peds:
            nums = sorted(
                r["numero"] for r in con.execute(
                    "SELECT numero FROM numeros WHERE pedido_id=?", (p["id"],)
                ).fetchall()
            )
            pedidos_out.append({
                "id": p["id"],
                "data": p["created_at"],
                "paid_at": p["paid_at"],
                "nome": p["nome"],
                "cpf": p["cpf"],
                "telefone": p["telefone"],
                "email": p["email"],
                "qtd": p["qtd"],
                "valor": p["valor"],
                "status": p["status"],
                "numeros": [_fmt_num(n) for n in nums],
            })
    return {
        "resumo": {
            "arrecadado": round(arrecadado, 2),
            "pedidos_pagos": pagos,
            "pedidos_pendentes": pendentes,
            "numeros_vendidos_reais": reais,
            "numeros_exibidos": VENDIDOS_FICTICIOS + reais,
            "total_numeros": TOTAL_NUMEROS,
            "ficticios": VENDIDOS_FICTICIOS,
        },
        "pedidos": pedidos_out,
    }


# ── Estático (site) ───────────────────────────────────────────────────
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE / "index.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(BASE / "admin.html")


app.mount("/", StaticFiles(directory=BASE, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # PORT vem do ambiente em produção (Render); host 0.0.0.0 para aceitar conexões externas
    port = int(os.environ.get("PORT", "4600"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
