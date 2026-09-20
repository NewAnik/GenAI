from __future__ import annotations

from decimal import Decimal
from typing import Annotated

import msgspec

PositiveInt = Annotated[int, msgspec.Meta(gt=0)]


class AddCartItemRequest(msgspec.Struct, kw_only=True):
    gift_box_slug: str
    quantity: PositiveInt


class UpdateCartItemRequest(msgspec.Struct, kw_only=True):
    quantity: PositiveInt


class CartItemResponse(msgspec.Struct, kw_only=True):
    id: int
    gift_box_slug: str | None = None
    name: str | None = None
    image_url: str | None = None
    alt_text: str | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class CartResponse(msgspec.Struct, kw_only=True):
    id: int
    status: str | None = None
    items: list[CartItemResponse] = msgspec.field(default_factory=list)
    subtotal: Decimal = Decimal("0")
