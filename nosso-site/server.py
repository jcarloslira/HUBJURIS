"""Backend standalone da Rifa Naeliton Prêmios.

Servidor próprio e independente: serve o site estático, gera Pix reais via
Mercado Pago (token no .env), sorteia números (1–58.000), permite ao cliente
consultar seus números e dá um painel admin para o Naeliton gerir tudo.
Sem Supabase, sem Emergent — persistência local em SQLite.

Rodar:  uv run python nosso-site/server.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
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
RECONCILIAR_A_CADA_SEG = 60     # rede de segurança: confere pendentes no MP
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


async def _confirmar_pedido(http: httpx.AsyncClient, payment_id: str) -> dict:
    """Consulta o pagamento no MP e sincroniza o pedido local. Idempotente.

    Aprovado -> marca pago e sorteia os números.
    Cancelado/rejeitado -> marca expirado (para de ser reconsultado).
    """
    if not MP_TOKEN:
        return {"payment_id": payment_id, "status": "sem_token", "numeros": []}

    r = await http.get(
        f"{MP_API}/{payment_id}", headers={"Authorization": f"Bearer {MP_TOKEN}"}
    )
    if r.status_code >= 400:
        return {"payment_id": payment_id, "status": "nao_encontrado", "numeros": []}

    status = r.json().get("status", "pending")
    numeros: list[int] = []
    with _db() as con:
        ped = con.execute(
            "SELECT * FROM pedidos WHERE mp_payment_id=?", (str(payment_id),)
        ).fetchone()
        if ped:
            if status == "approved":
                if ped["status"] != "pago":
                    con.execute(
                        "UPDATE pedidos SET status='pago', paid_at=? WHERE id=?",
                        (datetime.now(UTC).isoformat(), ped["id"]),
                    )
                numeros = _atribuir_numeros(con, ped)
            elif status in ("cancelled", "rejected", "refunded", "charged_back"):
                if ped["status"] == "pendente":
                    con.execute(
                        "UPDATE pedidos SET status='expirado' WHERE id=?", (ped["id"],)
                    )
    return {
        "payment_id": str(payment_id),
        "status": status,
        "numeros": [_fmt_num(n) for n in numeros],
    }


async def _reconciliar_pendentes(http: httpx.AsyncClient) -> list[dict]:
    """Rede de segurança: confere no MP todos os pedidos pendentes e libera números.

    Cobre o caso do cliente pagar e fechar a página antes da confirmação.
    """
    limite = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    with _db() as con:
        pendentes = con.execute(
            """SELECT mp_payment_id FROM pedidos
               WHERE status='pendente' AND mp_payment_id IS NOT NULL
                 AND created_at > ?""",
            (limite,),
        ).fetchall()

    resultados = []
    for row in pendentes:
        try:
            res = await _confirmar_pedido(http, row["mp_payment_id"])
            if res["status"] == "approved" or res["numeros"]:
                resultados.append(res)
        except Exception:  # noqa: BLE001 — nunca derrubar o loop por causa de 1 pedido
            continue
    return resultados


async def _loop_reconciliacao(app: FastAPI) -> None:
    """Roda a reconciliação periodicamente enquanto o servidor estiver de pé."""
    while True:
        await asyncio.sleep(RECONCILIAR_A_CADA_SEG)
        try:
            await _reconciliar_pendentes(app.state.http)
        except Exception:  # noqa: BLE001 — jamais interromper o loop
            continue


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


class PedidoManualIn(BaseModel):
    """Registro de compra paga FORA do site (ex.: PIX direto)."""
    nome: str = Field(min_length=2, max_length=120)
    cpf: str = Field(min_length=11, max_length=11)
    telefone: str = Field(default="", max_length=11)
    qtd: int = Field(ge=1, le=TOTAL_NUMEROS)


# ── App / lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    app.state.http = httpx.AsyncClient(timeout=20.0)
    # Rede de segurança: confere pendentes no MP mesmo se o cliente fechar a página
    tarefa = asyncio.create_task(_loop_reconciliacao(app))
    yield
    tarefa.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarefa
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
    res = await _confirmar_pedido(app.state.http, payment_id)
    if res["status"] == "nao_encontrado":
        raise HTTPException(status_code=404, detail="Pagamento não encontrado.")
    return res


@app.post("/api/webhook/mercadopago")
async def webhook_mercadopago(request: Request) -> dict:
    """Recebe o aviso do Mercado Pago quando o pagamento muda de estado.

    Confirma na hora, sem depender do cliente ficar com a página aberta.
    Aceita tanto o corpo JSON (`data.id`) quanto a query string (`data.id`).
    """
    payment_id: str | None = None
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — MP às vezes manda corpo vazio
        body = {}

    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and data.get("id"):
            payment_id = str(data["id"])
        elif body.get("id"):
            payment_id = str(body["id"])
    payment_id = payment_id or request.query_params.get("data.id") or request.query_params.get("id")

    if not payment_id:
        return {"ok": True, "ignorado": "sem payment_id"}

    try:
        res = await _confirmar_pedido(app.state.http, payment_id)
    except Exception:  # noqa: BLE001 — nunca devolver erro ao MP (evita reenvio infinito)
        return {"ok": True, "erro": "falha ao consultar"}
    return {"ok": True, "status": res["status"], "numeros": len(res["numeros"])}


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


BR_TZ = timezone(timedelta(hours=-3))
# Janela da promoção de engajamento (horário de Brasília)
JANELA_HORA_INICIO = 10  # 10h
JANELA_HORA_FIM = 22     # 22h


def _inicio_do_dia_br_utc() -> str:
    """Retorna o início do dia de hoje (00:00 no horário de Brasília) em UTC ISO."""
    br = datetime.now(UTC).astimezone(BR_TZ)
    inicio_br = br.replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio_br.astimezone(UTC).isoformat()


def _janela_hoje_br_utc() -> tuple[str, str]:
    """Janela de hoje das 10h às 22h (Brasília), devolvida em UTC ISO."""
    br = datetime.now(UTC).astimezone(BR_TZ)
    ini = br.replace(hour=JANELA_HORA_INICIO, minute=0, second=0, microsecond=0)
    fim = br.replace(hour=JANELA_HORA_FIM, minute=0, second=0, microsecond=0)
    return ini.astimezone(UTC).isoformat(), fim.astimezone(UTC).isoformat()


@app.get("/api/ranking")
async def ranking(periodo: str = "geral") -> list[dict]:
    """Ranking de compradores. periodo: 'geral', 'hoje' ou 'menor'.

    'menor' = quem POSSUI o menor NÚMERO de cota entre as compras da janela de
    hoje (10h–22h). Cada pessoa entra com a menor cota que tem; ordena crescente.
    Regras da promoção ficam só no Instagram.
    """
    if periodo == "menor":
        ini, fim = _janela_hoje_br_utc()
        # Filtra pela data em que a COMPRA foi feita (created_at), não pela
        # confirmação — assim pedidos antigos reconciliados hoje não vazam.
        # Agrupa por CPF (1 pessoa = 1 entrada, mesmo com nome digitado diferente)
        query = """SELECT n.nome AS nome, MIN(n.numero) AS menor
                   FROM numeros n
                   JOIN pedidos p ON p.id = n.pedido_id
                   WHERE p.status='pago' AND p.created_at >= ? AND p.created_at <= ?
                   GROUP BY n.cpf
                   ORDER BY menor ASC LIMIT 15"""
        with _db() as con:
            rows = con.execute(query, (ini, fim)).fetchall()
        return [{"nome": r["nome"], "cota": _fmt_num(r["menor"])} for r in rows]

    # Agrupa por CPF (1 pessoa = 1 entrada, mesmo com nome digitado diferente)
    if periodo == "hoje":
        query = """SELECT MAX(nome) AS nome, SUM(qtd) AS titulos
                   FROM pedidos WHERE status='pago' AND paid_at >= ?
                   GROUP BY cpf ORDER BY titulos DESC LIMIT 10"""
        params: tuple = (_inicio_do_dia_br_utc(),)
    else:
        query = """SELECT MAX(nome) AS nome, SUM(qtd) AS titulos
                   FROM pedidos WHERE status='pago'
                   GROUP BY cpf ORDER BY titulos DESC LIMIT 10"""
        params = ()
    with _db() as con:
        rows = con.execute(query, params).fetchall()
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
                "mp_payment_id": p["mp_payment_id"],
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


@app.post("/api/admin/pedido-manual")
async def pedido_manual(
    body: PedidoManualIn, x_admin_token: str | None = Header(default=None)
) -> dict:
    """Registra uma compra paga FORA do site e sorteia os números de verdade.

    Fica marcada como 'MANUAL' (pago por fora) para auditoria no painel.
    """
    _check_admin(x_admin_token)
    pedido_id = str(uuid.uuid4())
    agora = datetime.now(UTC).isoformat()
    valor = float((PRECO_TITULO * body.qtd).quantize(Decimal("0.01")))
    with _db() as con:
        con.execute(
            """INSERT INTO pedidos
               (id, mp_payment_id, qtd, valor, nome, cpf, telefone, email,
                status, qr_code, created_at, paid_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pedido_id, f"MANUAL-{pedido_id[:8]}", body.qtd, valor, body.nome,
                body.cpf, body.telefone, None, "pago", "", agora, agora,
            ),
        )
        ped = con.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()
        numeros = _atribuir_numeros(con, ped)
    return {
        "pedido_id": pedido_id,
        "nome": body.nome,
        "qtd": body.qtd,
        "valor": valor,
        "numeros": [_fmt_num(n) for n in numeros],
    }


@app.get("/api/admin/numero/{numero}")
async def admin_consultar_numero(
    numero: int, x_admin_token: str | None = Header(default=None)
) -> dict:
    """Descobre quem é o dono de uma cota/número (sorteio e prêmio instantâneo)."""
    _check_admin(x_admin_token)
    if numero < 1 or numero > TOTAL_NUMEROS:
        raise HTTPException(status_code=400, detail="Número fora do intervalo.")
    with _db() as con:
        row = con.execute(
            """SELECT n.numero AS numero, p.nome AS nome, p.cpf AS cpf,
                      p.telefone AS telefone, p.status AS status,
                      p.mp_payment_id AS mp, p.created_at AS data
               FROM numeros n JOIN pedidos p ON p.id = n.pedido_id
               WHERE n.numero = ?""",
            (numero,),
        ).fetchone()
    if not row:
        return {"numero": _fmt_num(numero), "disponivel": True}
    return {
        "numero": _fmt_num(numero),
        "disponivel": False,
        "nome": row["nome"],
        "cpf": row["cpf"],
        "telefone": row["telefone"],
        "por_fora": str(row["mp"] or "").startswith("MANUAL"),
        "data": row["data"],
    }


@app.post("/api/admin/reconciliar")
async def admin_reconciliar(x_admin_token: str | None = Header(default=None)) -> dict:
    """Confere agora todos os pendentes no Mercado Pago e libera números."""
    _check_admin(x_admin_token)
    corrigidos = await _reconciliar_pendentes(app.state.http)
    return {
        "corrigidos": len(corrigidos),
        "detalhes": [
            {"payment_id": c["payment_id"], "numeros": len(c["numeros"])}
            for c in corrigidos
        ],
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
