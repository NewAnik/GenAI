"""Persistent server-side cart access. One `active` cart per user; items reference a
`ProductVariant` and snapshot the variant price at add-time."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Cart, CartItem
from app.db.models.catalog import ProductVariant


class CartRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_or_create_active(self, user_id: int) -> Cart:
        cart = await self._get_active(user_id)
        if cart is not None:
            return cart
        self._session.add(Cart(user_id=user_id, status="active"))
        await self._session.flush()
        # Re-fetch through the eager-loading query so `.items` is loaded (never lazy-loaded
        # under async, which would raise MissingGreenlet).
        cart = await self._get_active(user_id)
        assert cart is not None  # just inserted in this transaction
        return cart

    async def _get_active(self, user_id: int) -> Cart | None:
        result = await self._session.execute(
            select(Cart)
            .options(selectinload(Cart.items).selectinload(CartItem.variant))
            .where(Cart.user_id == user_id, Cart.status == "active")
            .order_by(Cart.id.desc())
        )
        return result.scalars().first()

    async def get_item(self, item_id: int, *, cart_id: int) -> CartItem | None:
        result = await self._session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart_id)
        )
        return result.scalar_one_or_none()

    async def get_variant(self, variant_id: int) -> ProductVariant | None:
        result = await self._session.execute(
            select(ProductVariant)
            .options(selectinload(ProductVariant.product))
            .where(ProductVariant.id == variant_id)
        )
        return result.scalar_one_or_none()

    def add_item(self, item: CartItem) -> None:
        self._session.add(item)

    async def remove_item(self, item: CartItem) -> None:
        await self._session.delete(item)

    async def clear(self, cart: Cart) -> None:
        for item in list(cart.items):
            await self._session.delete(item)
        await self._session.flush()

    async def mark_checked_out(self, cart: Cart) -> None:
        cart.status = "checked_out"
        await self._session.flush()
