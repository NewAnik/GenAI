"""Storefront authentication: bcrypt password verification against `users.password_hash`
and stateless JWT issuance/decoding. Kept free of DB/FastAPI imports so it is unit-testable
in isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Raised for any authentication failure (bad credentials, invalid/expired token)."""


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _pwd_context.verify(plain, password_hash)
    except ValueError:
        # Malformed/unknown hash format stored in the DB — treat as a failed match.
        return False


def create_access_token(settings: Settings, *, user_id: int, org_id: int | None,
                        role: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": org_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(settings: Settings, token: str) -> dict:
    """Return the token claims, or raise AuthError on any invalid/expired/tampered token."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("invalid or expired token") from exc
