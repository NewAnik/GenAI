"""Storefront auth: Cognito is the identity source of truth. API Gateway's Cognito JWT
Authorizer verifies the bearer token before a handler ever runs, so this module only maps
verified claims onto (and provisions) the local `users` profile row, and checks group
membership for role-gated routes. No password hashing or JWT signing/verification lives
here — that's the whole point of the Cognito cutover (see the migration plan)."""
from __future__ import annotations

from storefront.db.models import User
from storefront.db.repositories.user_repo import UserRepository


class AuthError(Exception):
    """Raised when a request has no usable identity (missing/invalid claims, inactive user)."""


class ForbiddenError(Exception):
    """Raised when an authenticated user lacks a required group/role."""


def resolve_user(claims: dict) -> User:
    """Return the local `users` row for a verified Cognito identity, provisioning it if the
    PostConfirmation trigger (storefront/handlers/common/cognito_trigger.py) hasn't run yet
    — defensive; in normal operation it already has."""
    sub = claims.get("sub")
    if not sub:
        raise AuthError("token has no subject claim")

    repo = UserRepository()
    user = repo.get_by_cognito_sub(sub)
    if user is None:
        user = repo.create_from_cognito(cognito_sub=sub, email=claims.get("email"))
    if user.is_active is False:
        raise AuthError("user is inactive")
    return user


def require_group(claims: dict, *groups: str) -> None:
    user_groups = claims.get("cognito:groups") or []
    if isinstance(user_groups, str):
        user_groups = [user_groups]
    if not set(user_groups) & set(groups):
        raise ForbiddenError("insufficient group membership")
