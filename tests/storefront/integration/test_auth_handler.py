"""DB-backed tests for the auth Lambda's profile endpoints (skipped unless TEST_DATABASE_URL
is set — see conftest.py): reading /auth/me and editing the display name via
/auth/me/update."""
from __future__ import annotations

import json

from handlers import auth_handler
from local.fake_event import build_event


def _call(method, path, route_key, *, body=None, claims=None):
    event = build_event(method, path, route_key, body=body, claims=claims)
    resp = auth_handler.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _claims(cognito_sub: str) -> dict:
    return {"sub": cognito_sub}


def test_update_me_changes_first_and_last_name(seed):
    status, body = _call(
        "POST", "/auth/me/update", "POST /auth/me/update",
        body={"first_name": "Asha", "last_name": "Rao"}, claims=_claims(seed["cognito_sub"]),
    )
    assert status == 200
    assert body["first_name"] == "Asha"
    assert body["last_name"] == "Rao"

    # Persisted — a fresh /auth/me call reflects it too.
    status, body = _call("POST", "/auth/me", "POST /auth/me", claims=_claims(seed["cognito_sub"]))
    assert status == 200
    assert body["first_name"] == "Asha"
    assert body["last_name"] == "Rao"


def test_update_me_rejects_empty_name(seed):
    status, body = _call(
        "POST", "/auth/me/update", "POST /auth/me/update",
        body={"first_name": "", "last_name": "Rao"}, claims=_claims(seed["cognito_sub"]),
    )
    assert status == 422, body


def test_update_me_requires_auth():
    status, _ = _call(
        "POST", "/auth/me/update", "POST /auth/me/update",
        body={"first_name": "Asha", "last_name": "Rao"},
    )
    assert status in (401, 403)
