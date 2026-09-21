"""Peewee models for orders/quotes — used by dashboard_handler.py's aggregation and
quotes_handler.py's quote-to-order conversion transaction. The generic resource endpoint still
owns ordinary CRUD on these tables (see resource_service.py); these models exist only where a
bespoke handler needs a real transaction or a join the generic layer doesn't do."""
from __future__ import annotations

from peewee import CharField, DateTimeField, DecimalField, ForeignKeyField, IntegerField, TextField

from db.models.base import BaseModel
from db.models.catalog import Product
from db.models.users import User


class Org(BaseModel):
    class Meta:
        table_name = "org"

    name = CharField(null=True)


class Quote(BaseModel):
    class Meta:
        table_name = "quotes"

    organization = ForeignKeyField(Org, column_name="organization_id", null=True)
    quote_number = CharField(null=True)
    status = CharField(null=True)
    total_amount = DecimalField(null=True)
    created_by = ForeignKeyField(User, column_name="created_by", null=True)
    created_at = DateTimeField(null=True)


class QuoteItem(BaseModel):
    class Meta:
        table_name = "quote_items"

    quote = ForeignKeyField(Quote, backref="items", column_name="quote_id", null=True)
    product = ForeignKeyField(Product, column_name="product_id", null=True)
    quantity = IntegerField(null=True)
    unit_price = DecimalField(null=True)


class Order(BaseModel):
    class Meta:
        table_name = "orders"

    organization = ForeignKeyField(Org, column_name="organization_id", null=True)
    quote = ForeignKeyField(Quote, column_name="quote_id", null=True)
    order_number = CharField(null=True)
    status = CharField(null=True)
    offer_id = IntegerField(null=True)
    subtotal_amount = DecimalField(null=True)
    discount_amount = DecimalField(null=True)
    tax_amount = DecimalField(null=True)
    shipping_amount = DecimalField(null=True)
    total_amount = DecimalField(null=True)
    # Added for the website-order path (GenAI/alembic's 0002_website_orders.py) — a customer's own
    # order, not the org-facing quote-to-order path above. No Address model exists in this
    # package, so shipping_address_id stays a plain id (same treatment as offer_id above).
    user = ForeignKeyField(User, column_name="user_id", null=True)
    shipping_address_id = IntegerField(null=True)
    payment_status = CharField(null=True)
    created_at = DateTimeField(null=True)


class OrderItem(BaseModel):
    class Meta:
        table_name = "order_items"

    order = ForeignKeyField(Order, backref="items", column_name="order_id", null=True)
    product = ForeignKeyField(Product, column_name="product_id", null=True)
    quantity = IntegerField(null=True)
    unit_price = DecimalField(null=True)


class OrderStatusHistory(BaseModel):
    """One row per order-status transition — written here by orders_handler.py's bespoke
    status-change endpoint, and by GenAI/storefront on checkout. Read generically by the admin UI
    via config/resources.yml, and by the storefront's own order-detail endpoint."""

    class Meta:
        table_name = "order_status_history"

    order = ForeignKeyField(Order, backref="status_history", column_name="order_id", null=True)
    status = CharField(null=True)
    changed_by_user_id = IntegerField(null=True)
    changed_by_role = CharField(null=True)
    note = TextField(null=True)
    created_at = DateTimeField(null=True)
