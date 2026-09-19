"""Reads verified Cognito claims from the API Gateway authorizer context — the bearer token
was already verified by API Gateway's native REST API `CognitoUserPoolsAuthorizer` before
this Lambda ever ran, so no JWT library is needed in this package at all. REST API's Cognito
authorizer puts claims flat under `requestContext.authorizer.claims` (unlike HTTP API (v2)'s
JWT authorizer, which nests them one level deeper under an extra `jwt` key)."""
from __future__ import annotations

from db.models import User
from services.auth_service import require_group, resolve_user


def get_claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}


def get_current_user(event: dict) -> User:
    return resolve_user(get_claims(event))


def require_role(event: dict, *groups: str) -> User:
    claims = get_claims(event)
    user = resolve_user(claims)
    require_group(claims, *groups)
    return user
