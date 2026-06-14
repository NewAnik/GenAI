"""Integration test for the signed-webhook POST round trip: the GET verification handshake,
HMAC-SHA256 `X-Hub-Signature-256` enforcement, payload parsing, and background-task dispatch
to the orchestrator — exercised through a real FastAPI app over an in-process ASGI transport
(no real Meta/DB/LLM calls; the orchestrator and settings are overridden via FastAPI DI)."""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_orchestrator, get_settings_dep
from app.api.webhook import router as webhook_router
from app.config import Settings

_VERIFY_TOKEN = "test-verify-token"
_APP_SECRET = "test-app-secret"

_TEXT_MESSAGE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "entry-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "123"},
        "contacts": [{"profile": {"name": "Jane"}, "wa_id": "919800000000"}],
        "messages": [{"from": "919800000000", "id": "wamid.TEST1", "timestamp": "1700000000",
                      "type": "text", "text": {"body": "Hi, I need gifts for Diwali"}}],
    }}]}],
}

_STATUS_UPDATE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{"id": "entry-1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "123"},
        "statuses": [{"id": "wamid.STATUS1", "status": "delivered", "recipient_id": "919800000000"}],
    }}]}],
}


class _FakeOrchestrator:
    def __init__(self):
        self.handled = []

    async def handle_inbound(self, message):
        self.handled.append(message)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _build_app(orchestrator):
    app = FastAPI()
    app.include_router(webhook_router)
    app.dependency_overrides[get_settings_dep] = lambda: Settings(
        _env_file=None, meta_verify_token=_VERIFY_TOKEN, meta_app_secret=_APP_SECRET,
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_verify_webhook_handshake_succeeds_with_correct_token():
    app = _build_app(_FakeOrchestrator())
    async with _client(app) as client:
        response = await client.get("/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": _VERIFY_TOKEN, "hub.challenge": "12345",
        })

    assert response.status_code == 200
    assert response.text == "12345"


async def test_verify_webhook_handshake_rejects_wrong_token():
    app = _build_app(_FakeOrchestrator())
    async with _client(app) as client:
        response = await client.get("/webhook", params={
            "hub.mode": "subscribe", "hub.verify_token": "wrong-token", "hub.challenge": "12345",
        })

    assert response.status_code == 403


async def test_receive_webhook_accepts_correctly_signed_payload_and_dispatches_to_orchestrator():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = json.dumps(_TEXT_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign(body, _APP_SECRET), "Content-Type": "application/json"}

    async with _client(app) as client:
        response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 200
    assert len(orchestrator.handled) == 1
    assert orchestrator.handled[0].text == "Hi, I need gifts for Diwali"
    assert orchestrator.handled[0].whatsapp_number == "919800000000"


async def test_receive_webhook_rejects_payload_with_wrong_signature():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = json.dumps(_TEXT_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign(body, "a-completely-different-secret")}

    async with _client(app) as client:
        response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 403
    assert orchestrator.handled == []


async def test_receive_webhook_rejects_payload_with_missing_signature_header():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = json.dumps(_TEXT_MESSAGE_PAYLOAD).encode("utf-8")

    async with _client(app) as client:
        response = await client.post("/webhook", content=body)

    assert response.status_code == 403
    assert orchestrator.handled == []


async def test_receive_webhook_rejects_tampered_body_even_with_a_valid_looking_signature():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = json.dumps(_TEXT_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign(body, _APP_SECRET)}

    async with _client(app) as client:
        response = await client.post("/webhook", content=body + b'{"tampered": true}', headers=headers)

    assert response.status_code == 403
    assert orchestrator.handled == []


async def test_receive_webhook_returns_400_for_malformed_json_body():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = b"not-json-at-all"
    headers = {"X-Hub-Signature-256": _sign(body, _APP_SECRET)}

    async with _client(app) as client:
        response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 400
    assert orchestrator.handled == []


async def test_receive_webhook_acks_status_updates_and_still_dispatches_them():
    orchestrator = _FakeOrchestrator()
    app = _build_app(orchestrator)
    body = json.dumps(_STATUS_UPDATE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign(body, _APP_SECRET)}

    async with _client(app) as client:
        response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 200
    assert len(orchestrator.handled) == 1
    assert orchestrator.handled[0].message_type == "status_update"
    assert not orchestrator.handled[0].is_actionable
