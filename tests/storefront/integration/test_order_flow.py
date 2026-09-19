"""End-to-end order-flow integration tests against a real Postgres (skipped unless
TEST_DATABASE_URL is set — see conftest.py). Covers the happy path, the oversell guard,
cancellation/reservation-release, and the idempotent signed payment webhook.

Ported from tests/integration/test_order_flow.py: same scenarios, but calling Lambda
handlers directly with a synthetic API Gateway event (build_event) instead of an httpx
client, and Cognito claims instead of a bearer JWT.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

from storefront.handlers import cart_handler, orders_handler, payments_handler
from storefront.local.fake_event import build_event

_WEBHOOK_SECRET = "test-webhook-secret"


def _call(module, method, path, route_key, *, body=None, path_parameters=None,
          claims=None, headers=None, raw_body=None):
    event = build_event(
        method, path, route_key, body=body, path_parameters=path_parameters,
        claims=claims, headers=headers,
    )
    if raw_body is not None:
        event["body"] = raw_body.decode("utf-8")
    resp = module.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _claims(cognito_sub: str) -> dict:
    return {"sub": cognito_sub}


def _sign(body: bytes) -> str:
    digest = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _inventory_reserved(inventory_id: int) -> int:
    from storefront.db.models import Inventory

    return Inventory.get_by_id(inventory_id).reserved_quantity or 0


def test_full_order_flow_reserves_stock_and_confirms_on_payment(seed, monkeypatch):
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", _WEBHOOK_SECRET)
    from storefront.config import get_settings

    get_settings.cache_clear()
    claims = _claims(seed["cognito_sub"])

    # Add the one available unit to the cart.
    status, body = _call(
        cart_handler, "POST", "/cart/items", "POST /cart/items",
        body={"variant_id": seed["variant_id"], "quantity": 1}, claims=claims,
    )
    assert status == 201, body
    assert Decimal(body["subtotal"]) == Decimal("100")

    # Checkout -> order created, stock reserved.
    status, body = _call(
        orders_handler, "POST", "/checkout", "POST /checkout",
        body={"shipping_address_id": seed["address_id"]}, claims=claims,
    )
    assert status == 201, body
    order_id = body["order_id"]
    assert _inventory_reserved(seed["inventory_id"]) == 1

    # Order detail shows a pending order with an invoice.
    status, body = _call(
        orders_handler, "POST", f"/orders/{order_id}", "POST /orders/{order_id}",
        path_parameters={"order_id": str(order_id)}, claims=claims,
    )
    assert status == 200
    assert body["status"] == "pending"
    assert body["payment_status"] == "pending"
    assert body["invoice"] is not None
    # 100 + 18% GST
    assert Decimal(body["total_amount"]) == Decimal("118.00")

    # Record a payment reference, then fire the signed gateway webhook.
    status, body = _call(
        payments_handler, "POST", f"/orders/{order_id}/payments",
        "POST /orders/{order_id}/payments", path_parameters={"order_id": str(order_id)},
        body={"payment_method": "card", "transaction_reference": "txn_1", "amount": "118.00"},
        claims=claims,
    )
    assert status == 201, body

    payload = json.dumps({"transaction_reference": "txn_1", "status": "paid"}).encode()
    status, body = _call(
        payments_handler, "POST", "/webhooks/payments", "POST /webhooks/payments",
        raw_body=payload, headers={"x-signature-256": _sign(payload)},
    )
    assert status == 200
    assert body["status"] == "applied"

    # Replaying the same webhook is a no-op (idempotent).
    status, body = _call(
        payments_handler, "POST", "/webhooks/payments", "POST /webhooks/payments",
        raw_body=payload, headers={"x-signature-256": _sign(payload)},
    )
    assert body["status"] == "noop"

    status, body = _call(
        orders_handler, "POST", f"/orders/{order_id}", "POST /orders/{order_id}",
        path_parameters={"order_id": str(order_id)}, claims=claims,
    )
    assert body["payment_status"] == "paid"
    assert body["status"] == "confirmed"


def test_second_checkout_for_last_unit_conflicts(seed):
    # Buyer takes the only unit.
    claims1 = _claims(seed["cognito_sub"])
    _call(cart_handler, "POST", "/cart/items", "POST /cart/items",
          body={"variant_id": seed["variant_id"], "quantity": 1}, claims=claims1)
    status, _ = _call(orders_handler, "POST", "/checkout", "POST /checkout",
                       body={"shipping_address_id": seed["address_id"]}, claims=claims1)
    assert status == 201

    # A second buyer tries for the same (now fully reserved) variant.
    from storefront.db.models import Address, User

    user2 = User.create(email="buyer2@example.com", cognito_sub="sub-buyer-2",
                         role="customer", is_active=True)
    address2 = Address.create(user_id=user2.id, address_type="shipping", recipient_name="B2",
                               line1="2 Road", city="BLR", state="KA", pincode="560002")

    claims2 = _claims(user2.cognito_sub)
    _call(cart_handler, "POST", "/cart/items", "POST /cart/items",
          body={"variant_id": seed["variant_id"], "quantity": 1}, claims=claims2)
    status, body = _call(orders_handler, "POST", "/checkout", "POST /checkout",
                         body={"shipping_address_id": address2.id}, claims=claims2)
    assert status == 409, body
    # Reservation never exceeded on-hand stock.
    assert _inventory_reserved(seed["inventory_id"]) == 1


def test_cancel_releases_reserved_stock(seed):
    claims = _claims(seed["cognito_sub"])
    _call(cart_handler, "POST", "/cart/items", "POST /cart/items",
          body={"variant_id": seed["variant_id"], "quantity": 1}, claims=claims)
    status, body = _call(orders_handler, "POST", "/checkout", "POST /checkout",
                         body={"shipping_address_id": seed["address_id"]}, claims=claims)
    order_id = body["order_id"]
    assert _inventory_reserved(seed["inventory_id"]) == 1

    status, body = _call(orders_handler, "POST", f"/orders/{order_id}/cancel",
                         "POST /orders/{order_id}/cancel",
                         path_parameters={"order_id": str(order_id)}, claims=claims)
    assert status == 200
    assert body["status"] == "cancelled"
    assert _inventory_reserved(seed["inventory_id"]) == 0

    # Cancel is idempotent.
    status, _ = _call(orders_handler, "POST", f"/orders/{order_id}/cancel",
                      "POST /orders/{order_id}/cancel",
                      path_parameters={"order_id": str(order_id)}, claims=claims)
    assert status == 200


def test_empty_cart_checkout_is_rejected(seed):
    claims = _claims(seed["cognito_sub"])
    status, _ = _call(orders_handler, "POST", "/checkout", "POST /checkout",
                      body={"shipping_address_id": seed["address_id"]}, claims=claims)
    assert status == 400


def test_order_endpoints_require_auth(seed):
    status, _ = _call(orders_handler, "POST", "/orders", "POST /orders")
    assert status in (401, 403)
    status, _ = _call(cart_handler, "POST", "/cart", "POST /cart")
    assert status in (401, 403)
