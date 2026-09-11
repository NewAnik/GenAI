"""End-to-end order-flow integration tests against a real Postgres (skipped unless
TEST_DATABASE_URL is set — see conftest.py). Covers the happy path, the oversell guard,
cancellation/reservation-release, and the idempotent signed payment webhook."""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from app.config import get_settings

pytestmark = pytest.mark.asyncio

_WEBHOOK_SECRET = "test-webhook-secret"


async def _login(client, email: str, password: str = "pw") -> dict:
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _sign(body: bytes) -> str:
    digest = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _inventory_reserved(session_factory, inventory_id: int) -> int:
    from app.db.models import Inventory
    async with session_factory() as s:
        inv = await s.get(Inventory, inventory_id)
        return inv.reserved_quantity or 0


async def test_full_order_flow_reserves_stock_and_confirms_on_payment(client, seed, session_factory):
    headers = await _login(client, "buyer@example.com")

    # Add the one available unit to the cart.
    r = await client.post("/cart/items", json={"variant_id": seed["variant_id"], "quantity": 1},
                          headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["subtotal"] == "100"

    # Checkout -> order created, stock reserved.
    r = await client.post("/checkout", json={"shipping_address_id": seed["address_id"]},
                          headers=headers)
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]
    assert await _inventory_reserved(session_factory, seed["inventory_id"]) == 1

    # Order detail shows a pending order with an invoice.
    r = await client.get(f"/orders/{order_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["payment_status"] == "pending"
    assert body["invoice"] is not None
    # 100 + 18% GST
    assert Decimal(body["total_amount"]) == Decimal("118.00")

    # Record a payment reference, then fire the signed gateway webhook.
    r = await client.post(f"/orders/{order_id}/payments",
                          json={"payment_method": "card", "transaction_reference": "txn_1",
                                "amount": "118.00"}, headers=headers)
    assert r.status_code == 201, r.text

    get_settings().payment_webhook_secret = _WEBHOOK_SECRET
    payload = json.dumps({"transaction_reference": "txn_1", "status": "paid"}).encode()
    r = await client.post("/webhooks/payments", content=payload,
                          headers={"X-Signature-256": _sign(payload)})
    assert r.status_code == 200
    assert r.json()["status"] == "applied"

    # Replaying the same webhook is a no-op (idempotent).
    r = await client.post("/webhooks/payments", content=payload,
                          headers={"X-Signature-256": _sign(payload)})
    assert r.json()["status"] == "noop"

    r = await client.get(f"/orders/{order_id}", headers=headers)
    assert r.json()["payment_status"] == "paid"
    assert r.json()["status"] == "confirmed"


async def test_second_checkout_for_last_unit_conflicts(client, seed, session_factory):
    # Buyer takes the only unit.
    h1 = await _login(client, "buyer@example.com")
    await client.post("/cart/items", json={"variant_id": seed["variant_id"], "quantity": 1}, headers=h1)
    r = await client.post("/checkout", json={"shipping_address_id": seed["address_id"]}, headers=h1)
    assert r.status_code == 201

    # A second buyer tries for the same (now fully reserved) variant.
    from app.db.models import Address, User
    from app.services.auth_service import hash_password
    async with session_factory() as s:
        u2 = User(email="buyer2@example.com", password_hash=hash_password("pw"),
                  role="buyer", is_active=True)
        s.add(u2)
        await s.flush()
        a2 = Address(user_id=u2.id, address_type="shipping", recipient_name="B2",
                     line1="2 Road", city="BLR", state="KA", pincode="560002")
        s.add(a2)
        await s.commit()
        addr2_id = a2.id

    h2 = await _login(client, "buyer2@example.com")
    await client.post("/cart/items", json={"variant_id": seed["variant_id"], "quantity": 1}, headers=h2)
    r = await client.post("/checkout", json={"shipping_address_id": addr2_id}, headers=h2)
    assert r.status_code == 409, r.text
    # Reservation never exceeded on-hand stock.
    assert await _inventory_reserved(session_factory, seed["inventory_id"]) == 1


async def test_cancel_releases_reserved_stock(client, seed, session_factory):
    headers = await _login(client, "buyer@example.com")
    await client.post("/cart/items", json={"variant_id": seed["variant_id"], "quantity": 1}, headers=headers)
    r = await client.post("/checkout", json={"shipping_address_id": seed["address_id"]}, headers=headers)
    order_id = r.json()["order_id"]
    assert await _inventory_reserved(session_factory, seed["inventory_id"]) == 1

    r = await client.post(f"/orders/{order_id}/cancel", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert await _inventory_reserved(session_factory, seed["inventory_id"]) == 0

    # Cancel is idempotent.
    r = await client.post(f"/orders/{order_id}/cancel", headers=headers)
    assert r.status_code == 200


async def test_empty_cart_checkout_is_rejected(client, seed):
    headers = await _login(client, "buyer@example.com")
    r = await client.post("/checkout", json={"shipping_address_id": seed["address_id"]}, headers=headers)
    assert r.status_code == 400


async def test_order_endpoints_require_auth(client, seed):
    assert (await client.get("/orders")).status_code in (401, 403)
    assert (await client.get("/cart")).status_code in (401, 403)
