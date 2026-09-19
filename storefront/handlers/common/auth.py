"""Reads verified Cognito claims from the API Gateway authorizer context — the bearer token
was already verified by API Gateway's native Cognito JWT Authorizer before this Lambda ever
ran, so no JWT library is needed in this package at all."""
from __future__ import annotations

from storefront.db.models import User
from storefront.services.auth_service import require_group, resolve_user


def get_claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    ) or {}


def get_current_user(event: dict) -> User:
    return resolve_user(get_claims(event))


def require_role(event: dict, *groups: str) -> User:
    claims = get_claims(event)
    user = resolve_user(claims)
    require_group(claims, *groups)
    return user
