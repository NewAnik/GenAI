from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin


class Warehouse(CreatedAtMixin, Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    reserved_quantity: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())


class Supplier(CreatedAtMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String)
    contact_person: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    gst_number: Mapped[str | None] = mapped_column(String)


class SupplierProduct(Base):
    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    supplier_price: Mapped[Decimal | None] = mapped_column(Numeric)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)

    supplier: Mapped["Supplier | None"] = relationship()
    # String forward-ref to catalog.Product — resolved when app.db.models registers all
    # mapped classes (see app/db/models/__init__.py); avoids a circular import here.
    product: Mapped["Product"] = relationship()  # noqa: F821
