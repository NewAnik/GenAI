"""Admin API auth: Cognito is the identity source of truth. API Gateway's CognitoUserPoolsAuthorizer
verifies the bearer token before a handler ever runs (bound to the Admin User Pool — see
admin_cognito_stack.py — never the storefront's customer pool), so this module only maps verified
claims onto the local staff profile row and checks group membership for role-gated operations.

Unlike storefront/services/auth_service.py's `resolve_user` (which defensively creates a local row
for any verified customer), `resolve_staff_user` never auto-provisions: a staff row must only ever
be created through the explicit provisioning path
(wrapped-and-more-admin/scripts/provision-staff.mjs), never implicitly on first request — a
Cognito principal from the Admin User Pool with no matching local `users.cognito_sub` row is a
hard 401, not a shortcut into staff access."""
from __future__ import annotations

from db.models.users import User
from db.repositories.user_repo import UserRepository

_repo = UserRepository()


class AuthError(Exception):
    """Raised when a request has no usable staff identity (missing/invalid claims, no matching
    local row, or an inactive account)."""


class ForbiddenError(Exception):
    """Raised when an authenticated staff member lacks a required group/role for the operation."""


def resolve_staff_user(claims: dict) -> User:
    sub = claims.get("sub")
    if not sub:
        raise AuthError("token has no subject claim")

    user = _repo.get_by_cognito_sub(sub)
    if user is None:
        raise AuthError("no staff profile is provisioned for this account")
    if not user.is_active:
        raise AuthError("staff account is inactive")
    return user


def user_groups(claims: dict) -> set[str]:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return set(groups)


def require_group(claims: dict, *groups: str) -> None:
    if not groups:
        # An empty required-groups list (e.g. resources.yml's audit_logs.create_groups: []) can
        # never be satisfied — this is the single mechanism "no one may do this" is expressed
        # with, same as "only these roles may."
        raise ForbiddenError("this operation is not permitted through the API")
    if not user_groups(claims) & set(groups):
        raise ForbiddenError("insufficient group membership")
