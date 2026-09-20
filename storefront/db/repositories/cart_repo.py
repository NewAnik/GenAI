"""Persistent server-side cart access. One `active` cart per user; items reference a GiftBox
(the sellable unit) and snapshot its selling price at add-time.

Peewee note: unlike the async SQLAlchemy version this ports from (app/db/repositories/
cart_repo.py), lazy relationship access (`item.gift_box`) is safe to call directly here —
Peewee is sync, so there's no MissingGreenlet risk the original's eager-loading/re-fetch
dance was working around. This does mean one query per cart item to resolve `.gift_box`;
negligible at the cart sizes this endpoint sees, so no prefetch is used.
"""
from __future__ import annotations

from decimal import Decimal

from db.models import Cart, CartItem


class CartRepository:
    def get_or_create_active(self, user_id: int) -> Cart:
        cart = self._get_active(user_id)
        if cart is not None:
            return cart
        return Cart.create(user_id=user_id, status="active")

    def _get_active(self, user_id: int) -> Cart | None:
        return (
            Cart.select()
            .where(Cart.user_id == user_id, Cart.status == "active")
            .order_by(Cart.id.desc())
            .first()
        )

    def items_for(self, cart: Cart) -> list[CartItem]:
        return list(CartItem.select().where(CartItem.cart == cart))

    def get_item(self, item_id: int, *, cart_id: int) -> CartItem | None:
        return CartItem.get_or_none(CartItem.id == item_id, CartItem.cart_id == cart_id)

    def add_item(self, *, cart_id: int, gift_box_id: int, quantity: int,
                 unit_price_snapshot: Decimal) -> CartItem:
        return CartItem.create(
            cart_id=cart_id, gift_box_id=gift_box_id, quantity=quantity,
            unit_price_snapshot=unit_price_snapshot,
        )

    def remove_item(self, item: CartItem) -> None:
        item.delete_instance()

    def clear(self, cart: Cart) -> None:
        CartItem.delete().where(CartItem.cart == cart).execute()

    def mark_checked_out(self, cart: Cart) -> None:
        cart.status = "checked_out"
        cart.save()
