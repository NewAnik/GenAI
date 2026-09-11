"""Storefront authentication endpoints: email/password login issuing a JWT, and the
current-user probe."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings_dep
from app.config import Settings
from app.db.models import User
from app.db.repositories.user_repo import UserRepository
from app.logging_setup import get_logger
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import create_access_token, verify_password

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, settings: Settings = Depends(get_settings_dep),
                db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await UserRepository(db).get_by_email(payload.email)
    if user is None or user.is_active is False or not verify_password(payload.password, user.password_hash):
        # Uniform error so callers can't distinguish unknown-email from wrong-password.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    token = create_access_token(settings, user_id=user.id, org_id=user.organization_id, role=user.role)
    logger.info("user_logged_in", user_id=user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, first_name=user.first_name,
        last_name=user.last_name, role=user.role, organization_id=user.organization_id,
    )
