from __future__ import annotations

from decimal import Decimal

import msgspec


class RecordPaymentRequest(msgspec.Struct, kw_only=True):
    payment_method: str
    transaction_reference: str
    amount: Decimal


def ensure_positive_amount(amount: Decimal) -> None:
    """msgspec's `Meta(gt=...)` constraint only applies to int/float, not Decimal (it raises
    TypeError at decode-time if attached to a Decimal field) — so the original Pydantic
    schema's `Field(gt=0)` check is enforced here instead, called explicitly by the handler
    after decoding."""
    if amount <= 0:
        raise ValueError("amount must be positive")


class PaymentResponse(msgspec.Struct, kw_only=True):
    id: int
    order_id: int | None = None
    payment_method: str | None = None
    payment_status: str | None = None
    transaction_reference: str | None = None
    amount: Decimal | None = None
