"""Lambda for POST /auth/me and POST /auth/me/update. Login/signup happen directly against
Cognito from the client (SignUp/InitiateAuth) — this Lambda only ever serves and edits the
local profile for an already-authenticated user; Cognito itself is never touched here, since
first/last name are display-only fields, not credentials. Every route in this API is POST, by
design — see infra/config/functions.yml's header comment."""
from __future__ import annotations

from db.database import connection
from db.repositories.user_repo import UserRepository
from handlers.common.auth import get_current_user
from handlers.common.http import decode_body, json_response
from handlers.common.router import dispatch
from schemas.auth import UpdateUserRequest, UserResponse

_repo = UserRepository()


def _serialize(user) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=user.role, organization_id=user.organization_id,
    )


def _me(event: dict) -> dict:
    user = get_current_user(event)
    return json_response(200, _serialize(user))


def _update_me(event: dict) -> dict:
    user = get_current_user(event)
    payload = decode_body(event, UpdateUserRequest)
    _repo.update_name(user, first_name=payload.first_name, last_name=payload.last_name)
    return json_response(200, _serialize(user))


ROUTES = {
    "POST /auth/me": _me,
    "POST /auth/me/update": _update_me,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES, context)
