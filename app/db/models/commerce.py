from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin


class Quote(CreatedAtMixin, Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("org.id"))
    quote_number: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["QuoteItem"]] = relationship(back_populates="quote")


class QuoteItem(Base):
    __tablename__ = "quote_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric)

    quote: Mapped["Quote | None"] = relationship(back_populates="items")
    # String forward-ref to catalog.Product — resolved via the declarative registry once
    # app.db.models imports every model module; avoids a circular import here.
    product: Mapped["Product"] = relationship()  # noqa: F821


class Order(CreatedAtMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("org.id"))
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    order_number: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    # Added for the website order flow (alembic 0002): the buyer, the chosen shipping
    # address, and a denormalized payment status for cheap listing/filtering.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    shipping_address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id"))
    payment_status: Mapped[str | None] = mapped_column(String)

    items: Mapped[list["OrderItem"]] = relationship()


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric)
    # Added for the website order flow (alembic 0002): the exact variant purchased, so
    # cancel/fulfillment can release/decrement the correct inventory row (inventory is
    # tracked per variant, while the base order_items schema only carried product_id).
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    payment_method: Mapped[str | None] = mapped_column(String)
    payment_status: Mapped[str | None] = mapped_column(String)
    transaction_reference: Mapped[str | None] = mapped_column(String)
    amount: Mapped[Decimal | None] = mapped_column(Numeric)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    invoice_number: Mapped[str | None] = mapped_column(String)
    invoice_url: Mapped[str | None] = mapped_column(Text)
    gst_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    courier_name: Mapped[str | None] = mapped_column(String)
    tracking_number: Mapped[str | None] = mapped_column(String)
    shipment_status: Mapped[str | None] = mapped_column(String)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
