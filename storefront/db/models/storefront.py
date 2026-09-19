"""Website storefront tables: a persistent server-side cart (one active cart per user) and
reusable shipping/billing addresses. See app/db/models/storefront.py for the SQLAlchemy
original this ports from."""
from __future__ import annotations

from peewee import CharField, DateTimeField, DecimalField, ForeignKeyField, IntegerField, TextField

from storefront.db.models.base import BaseModel, TimestampMixin
from storefront.db.models.catalog import ProductVariant
from storefront.db.models.users import User


class Address(TimestampMixin):
    class Meta:
        table_name = "addresses"

    user = ForeignKeyField(User, backref="addresses", column_name="user_id", null=True)
    address_type = CharField(null=True)  # "shipping" | "billing"
    recipient_name = CharField(null=True)
    phone = CharField(null=True)
    line1 = TextField(null=True)
    line2 = TextField(null=True)
    city = CharField(null=True)
    state = CharField(null=True)
    pincode = CharField(null=True)


class Cart(TimestampMixin):
    class Meta:
        table_name = "carts"

    user = ForeignKeyField(User, backref="carts", column_name="user_id", null=True)
    status = CharField(null=True, default="active")  # active | checked_out


class CartItem(BaseModel):
    class Meta:
        table_name = "cart_items"

    cart = ForeignKeyField(Cart, backref="items", column_name="cart_id", null=True)
    variant = ForeignKeyField(ProductVariant, backref="cart_items", column_name="variant_id", null=True)
    quantity = IntegerField(null=True)
    # Price captured when the item was added, so cart totals are stable even if the
    # catalog price later changes; re-validated at checkout.
    unit_price_snapshot = DecimalField(max_digits=12, decimal_places=2, null=True)
    created_at = DateTimeField(null=True)
