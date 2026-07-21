"""Lógica de contas: cadastro, login (Supabase Auth/GoTrue), equipe e uso.

Fala com o GoTrue por REST (httpx) em vez de mutar o estado de auth do client
Supabase compartilhado. A criação de usuário usa a admin API (service_role)
com ``email_confirm`` para o acesso funcionar imediatamente, sem depender de
e-mail de confirmação.
"""

import httpx
from supabase import AsyncClient

from app.config import Settings
from app.schemas.contas import (
    LoginPayload,
    MembroCreate,
    MembroResponse,
    PerfilResponse,
    SessaoResponse,
    SignupPayload,
    UsoModelo,
    UsoResumo,
)


class ContaError(Exception):
    """Erro de negócio em contas (e-mail em uso, credenciais inválidas...)."""

    def __init__(self, mensagem: str, status: int = 400) -> None:
        super().__init__(mensagem)
        self.status = status


class ContaService:
    """Cadastro, login, perfil, equipe e medição de uso por escritório."""

    def __init__(self, supabase: AsyncClient, http: httpx.AsyncClient, settings: Settings) -> None:
        self._db = supabase
        self._http = http
        self._url = settings.SUPABASE_URL.rstrip("/")
        self._anon = settings.SUPABASE_ANON_KEY
        self._service = settings.SUPABASE_SERVICE_ROLE_KEY

    # ── Auth (GoTrue REST) ──────────────────────────────────────

    async def _criar_usuario_auth(self, email: str, senha: str) -> str:
        """Cria o usuário no Supabase Auth já confirmado; retorna o user_id."""
        try:
            resp = await self._http.post(
                f"{self._url}/auth/v1/admin/users",
                headers={"apikey": self._service, "Authorization": f"Bearer {self._service}"},
                json={"email": email, "password": senha, "email_confirm": True},
            )
        except httpx.HTTPError as exc:
            raise ContaError(
                "Sem conexão com o servidor de autenticação — verifique a internet.",
                status=503,
            ) from exc
        dados = resp.json()
        if resp.status_code >= 400:
            msg = str(dados.get("msg") or dados.get("message") or dados)
            if "already" in msg.lower() or resp.status_code == 422:
                raise ContaError("E-mail já cadastrado", status=409)
            raise ContaError(f"Falha ao criar usuário: {msg}", status=502)
        return str(dados["id"])

    async def _login_auth(self, email: str, senha: str) -> str:
        """Autentica no GoTrue e retorna o access_token."""
        try:
            resp = await self._http.post(
                f"{self._url}/auth/v1/token?grant_type=password",
                headers={"apikey": self._anon},
                json={"email": email, "password": senha},
            )
        except httpx.HTTPError as exc:
            raise ContaError(
                "Sem conexão com o servidor de autenticação — verifique a internet.",
                status=503,
            ) from exc
        dados = resp.json()
        if resp.status_code >= 400 or "access_token" not in dados:
            raise ContaError("E-mail ou senha incorretos", status=401)
        return str(dados["access_token"])

    # ── Fluxos ──────────────────────────────────────────────────

    async def signup(self, payload: SignupPayload) -> SessaoResponse:
        """Cadastro inicial: usuário admin + escritório + membro + sessão."""
        user_id = await self._criar_usuario_auth(payload.email, payload.senha)

        esc = (
            await self._db.table("escritorios").insert({"nome": payload.nome_escritorio}).execute()
        )
        escritorio = (esc.data or [{}])[0]
        escritorio_id = str(escritorio.get("id"))

        await self._db.table("membros").insert(
            {
                "user_id": user_id,
                "escritorio_id": escritorio_id,
                "nome": payload.nome,
                "email": payload.email,
                "papel": "admin",
            }
        ).execute()

        token = await self._login_auth(payload.email, payload.senha)
        perfil = PerfilResponse(
            user_id=user_id,
            nome=payload.nome,
            email=payload.email,
            papel="admin",
            escritorio_id=escritorio_id,
            escritorio_nome=payload.nome_escritorio,
        )
        return SessaoResponse(access_token=token, perfil=perfil)

    async def login(self, payload: LoginPayload) -> SessaoResponse:
        """Login: valida credenciais e devolve token + perfil."""
        token = await self._login_auth(payload.email, payload.senha)
        result = await self._db.table("membros").select("*").eq("email", payload.email).execute()
        rows = result.data or []
        if not rows:
            raise ContaError("Usuário sem perfil no LexHub", status=403)
        return SessaoResponse(access_token=token, perfil=await self._montar_perfil(rows[0]))

    async def perfil(self, user_id: str) -> PerfilResponse:
        """Perfil do usuário logado (via user_id validado pelo JWT)."""
        result = await self._db.table("membros").select("*").eq("user_id", user_id).execute()
        rows = result.data or []
        if not rows:
            raise ContaError("Usuário sem perfil no LexHub", status=403)
        return await self._montar_perfil(rows[0])

    async def _montar_perfil(self, membro: dict) -> PerfilResponse:
        esc = (
            await self._db.table("escritorios")
            .select("nome")
            .eq("id", membro["escritorio_id"])
            .execute()
        )
        nome_esc = ((esc.data or [{}])[0]).get("nome", "")
        return PerfilResponse(
            user_id=str(membro["user_id"]),
            nome=membro["nome"],
            email=membro["email"],
            papel=membro["papel"],
            escritorio_id=str(membro["escritorio_id"]),
            escritorio_nome=nome_esc,
        )

    # ── Equipe ──────────────────────────────────────────────────

    async def listar_membros(self, escritorio_id: str) -> list[MembroResponse]:
        """Equipe do escritório."""
        result = (
            await self._db.table("membros")
            .select("*")
            .eq("escritorio_id", escritorio_id)
            .order("created_at")
            .execute()
        )
        return [MembroResponse.model_validate(m) for m in (result.data or [])]

    async def criar_membro(self, escritorio_id: str, payload: MembroCreate) -> MembroResponse:
        """Admin cadastra um membro da equipe no mesmo escritório."""
        user_id = await self._criar_usuario_auth(payload.email, payload.senha)
        await self._db.table("membros").insert(
            {
                "user_id": user_id,
                "escritorio_id": escritorio_id,
                "nome": payload.nome,
                "email": payload.email,
                "papel": payload.papel,
            }
        ).execute()
        return MembroResponse(
            user_id=user_id, nome=payload.nome, email=payload.email, papel=payload.papel
        )

    # ── Uso de tokens ───────────────────────────────────────────

    async def registrar_uso(
        self,
        *,
        escritorio_id: str | None,
        user_id: str | None,
        agente: str,
        modelo: str,
        tokens_entrada: int,
        tokens_saida: int,
    ) -> None:
        """Grava o consumo real de uma chamada (medido pela API da Anthropic)."""
        await self._db.table("uso_tokens").insert(
            {
                "escritorio_id": escritorio_id,
                "user_id": user_id,
                "agente": agente,
                "modelo": modelo,
                "tokens_entrada": tokens_entrada,
                "tokens_saida": tokens_saida,
            }
        ).execute()

    async def resumo_uso(self, escritorio_id: str) -> UsoResumo:
        """Totais de tokens do escritório, geral e por modelo."""
        result = (
            await self._db.table("uso_tokens")
            .select("modelo,tokens_entrada,tokens_saida")
            .eq("escritorio_id", escritorio_id)
            .execute()
        )
        rows = result.data or []
        por_modelo: dict[str, dict[str, int]] = {}
        total_in = total_out = 0
        for r in rows:
            modelo = r.get("modelo") or "desconhecido"
            item = por_modelo.setdefault(modelo, {"in": 0, "out": 0})
            item["in"] += int(r.get("tokens_entrada") or 0)
            item["out"] += int(r.get("tokens_saida") or 0)
            total_in += int(r.get("tokens_entrada") or 0)
            total_out += int(r.get("tokens_saida") or 0)
        return UsoResumo(
            total_entrada=total_in,
            total_saida=total_out,
            por_modelo=[
                UsoModelo(modelo=m, tokens_entrada=v["in"], tokens_saida=v["out"])
                for m, v in sorted(por_modelo.items())
            ],
        )
