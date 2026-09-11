from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class RecordPaymentRequest(BaseModel):
    payment_method: str
    transaction_reference: str
    amount: Decimal = Field(gt=0)


class PaymentResponse(BaseModel):
    id: int
    order_id: int | None = None
    payment_method: str | None = None
    payment_status: str | None = None
    transaction_reference: str | None = None
    amount: Decimal | None = None
