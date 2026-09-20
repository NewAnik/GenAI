"""Reads verified Cognito claims from the API Gateway authorizer context — copied verbatim from
storefront/handlers/common/auth.py's shape, adapted to the admin API's staff-only resolution
(no auto-provisioning — see services/auth_service.py's docstring)."""
from __future__ import annotations

from db.models.users import User
from services.auth_service import require_group, resolve_staff_user


def get_claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}


def get_current_user(event: dict) -> User:
    return resolve_staff_user(get_claims(event))


def require_role(event: dict, *groups: str) -> User:
    claims = get_claims(event)
    user = resolve_staff_user(claims)
    require_group(claims, *groups)
    return user
