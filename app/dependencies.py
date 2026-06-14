"""Dependências FastAPI: autenticação e cliente Supabase."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AsyncClient

from app.schemas.auth import AuthUser

bearer_scheme = HTTPBearer()


async def get_supabase(request: Request) -> AsyncClient:
    """Retorna o cliente Supabase inicializado no lifespan da aplicação.

    Raises:
        HTTPException: 503 se o Supabase não estiver configurado (modo demo).
    """
    supabase: AsyncClient | None = request.app.state.supabase
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase não configurado — recurso disponível apenas com contas ativas",
        )
    return supabase


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    supabase: Annotated[AsyncClient, Depends(get_supabase)],
) -> AuthUser:
    """Valida o JWT do Supabase Auth e retorna o usuário autenticado.

    Args:
        credentials: Token Bearer extraído do header Authorization.
        supabase: Cliente Supabase da aplicação.

    Returns:
        Usuário autenticado.

    Raises:
        HTTPException: 401 se o token for inválido ou expirado.
    """
    try:
        response = await supabase.auth.get_user(credentials.credentials)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        ) from exc

    if response is None or response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        )

    return AuthUser.model_validate(response.user)
