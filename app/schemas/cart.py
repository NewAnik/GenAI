from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class AddCartItemRequest(BaseModel):
    variant_id: int
    quantity: int = Field(gt=0)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(gt=0)


class CartItemResponse(BaseModel):
    id: int
    variant_id: int | None = None
    sku: str | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class CartResponse(BaseModel):
    id: int
    status: str | None = None
    items: list[CartItemResponse] = []
    subtotal: Decimal = Decimal("0")
