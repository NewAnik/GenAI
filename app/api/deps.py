"""FastAPI dependency providers — thin accessors over objects constructed once at startup
and stored on `app.state` (see `app.main.create_app`), plus cached settings, the per-request
DB session, and JWT auth."""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Request, status
from fastapi.exceptions import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import User
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session
from app.services.auth_service import AuthError, decode_access_token
from app.services.conversation_orchestrator import ConversationOrchestrator

_bearer = HTTPBearer(auto_error=False)


def get_settings_dep() -> Settings:
    return get_settings()


def get_orchestrator(request: Request) -> ConversationOrchestrator:
    return request.app.state.orchestrator


async def get_db() -> AsyncIterator[AsyncSession]:
    """Per-request DB session for read/simple-write endpoints. Commits on clean exit and
    rolls back on error, matching `get_session()`. (Multi-step atomic flows like checkout
    open their own transaction inside the service layer instead.)"""
    async with get_session() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    try:
        claims = decode_access_token(settings, credentials.credentials)
    except AuthError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")

    try:
        user_id = int(claims.get("sub", ""))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token subject")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None or user.is_active is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found or inactive")
    return user


def require_role(*roles: str):
    """Dependency factory gating an endpoint to users whose `role` is in `roles`."""
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return user
    return _dep
