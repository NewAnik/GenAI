"""Website storefront tables added for the transactional order flow: a persistent
server-side cart (one active cart per user) and reusable shipping/billing addresses.

These are net-new tables (see alembic 0002); the rest of the commerce lifecycle
(orders, payments, invoices, shipments) already exists in `commerce.py`."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin


class Address(TimestampMixin, Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    address_type: Mapped[str | None] = mapped_column(String)  # "shipping" | "billing"
    recipient_name: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    line1: Mapped[str | None] = mapped_column(Text)
    line2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    pincode: Mapped[str | None] = mapped_column(String)


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str | None] = mapped_column(String, default="active")  # active | checked_out

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int | None] = mapped_column(ForeignKey("carts.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    # Price captured when the item was added, so cart totals are stable even if the
    # catalog price later changes; re-validated at checkout.
    unit_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), server_default=func.now()
    )

    cart: Mapped["Cart | None"] = relationship(back_populates="items")
    # String forward-ref to catalog.ProductVariant — resolved once app.db.models imports
    # every model module (see app/db/models/__init__.py); avoids a circular import here.
    variant: Mapped["ProductVariant"] = relationship()  # noqa: F821
