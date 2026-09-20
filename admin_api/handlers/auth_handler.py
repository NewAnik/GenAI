"""Lambda for POST /auth/me — the admin app's replacement for AuthProvider.tsx's direct
`supabase.from('users').select(...)` profile query. Login/logout happen directly against Cognito
from the client; this Lambda only ever serves the local staff profile for an
already-authenticated user, and (unlike storefront's auth_handler.py) never auto-provisions one —
see services/auth_service.py's docstring."""
from __future__ import annotations

from db.connection import connection
from handlers.common.auth import get_current_user
from handlers.common.http import json_response
from handlers.common.router import dispatch


def _serialize(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
        "organization_id": user.organization_id,
        "is_active": user.is_active,
    }


def _me(event: dict) -> dict:
    user = get_current_user(event)
    return json_response(200, _serialize(user))


ROUTES = {
    "POST /auth/me": _me,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
