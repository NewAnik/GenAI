"""msgspec schema encode/decode sanity checks. msgspec's JSON handling of Decimal/`gt=`
constraints differs mechanically from Pydantic's `model_dump(mode="json")`/`Field(gt=0)` —
this pins the actual behavior down so a future msgspec upgrade can't silently change it."""
from __future__ import annotations

from decimal import Decimal

import msgspec
import pytest

from schemas.cart import AddCartItemRequest, CartResponse
from schemas.payment import RecordPaymentRequest, ensure_positive_amount


def test_decimal_round_trips_through_json():
    resp = CartResponse(id=1, status="active", items=[], subtotal=Decimal("118.00"))
    encoded = msgspec.json.encode(resp)
    decoded = msgspec.json.decode(encoded, type=CartResponse)
    assert decoded.subtotal == Decimal("118.00")


def test_positive_int_constraint_is_enforced():
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(b'{"variant_id": 1, "quantity": 0}', type=AddCartItemRequest)


def test_positive_int_constraint_allows_positive_values():
    parsed = msgspec.json.decode(b'{"variant_id": 1, "quantity": 3}', type=AddCartItemRequest)
    assert parsed.quantity == 3


def test_amount_decodes_regardless_of_sign():
    # msgspec's `Meta(gt=...)` doesn't apply to Decimal, so decoding a non-positive amount
    # succeeds — ensure_positive_amount() is what actually enforces `Field(gt=0)` parity,
    # called explicitly by the handler (see test_ensure_positive_amount_* below).
    parsed = msgspec.json.decode(
        b'{"payment_method": "card", "transaction_reference": "t1", "amount": "-5"}',
        type=RecordPaymentRequest,
    )
    assert parsed.amount == Decimal("-5")


def test_ensure_positive_amount_rejects_non_positive():
    with pytest.raises(ValueError):
        ensure_positive_amount(Decimal("0"))
    with pytest.raises(ValueError):
        ensure_positive_amount(Decimal("-5"))


def test_ensure_positive_amount_allows_positive():
    ensure_positive_amount(Decimal("0.01"))
