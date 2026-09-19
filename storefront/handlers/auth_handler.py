"""Lambda for POST /auth/me. Login/signup happen directly against Cognito from the client
(SignUp/InitiateAuth) — this Lambda only ever serves the local profile for an
already-authenticated user. Every route in this API is POST, by design — see
infra/config/functions.yml's header comment."""
from __future__ import annotations

from storefront.db.database import connection
from storefront.handlers.common.auth import get_current_user
from storefront.handlers.common.http import json_response
from storefront.handlers.common.router import dispatch
from storefront.schemas.auth import UserResponse


def _me(event: dict) -> dict:
    user = get_current_user(event)
    return json_response(200, UserResponse(
        id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name,
        role=user.role, organization_id=user.organization_id,
    ))


ROUTES = {"POST /auth/me": _me}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
