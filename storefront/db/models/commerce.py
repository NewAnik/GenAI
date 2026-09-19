"""Order / order-item / payment / invoice / shipment. `Quote`/`QuoteItem` (commerce.py in
the SQLAlchemy original) aren't touched by any in-scope repo/service and are skipped."""
from __future__ import annotations

from peewee import CharField, DateTimeField, DecimalField, ForeignKeyField, IntegerField, TextField

from storefront.db.models.base import BaseModel, CreatedAtMixin
from storefront.db.models.catalog import Product, ProductVariant
from storefront.db.models.storefront import Address
from storefront.db.models.users import User


class Order(CreatedAtMixin):
    class Meta:
        table_name = "orders"

    organization_id = IntegerField(null=True)
    quote_id = IntegerField(null=True)
    order_number = CharField(null=True)
    status = CharField(null=True)
    total_amount = DecimalField(max_digits=12, decimal_places=2, null=True)
    user = ForeignKeyField(User, backref="orders", column_name="user_id", null=True)
    shipping_address = ForeignKeyField(
        Address, backref="orders", column_name="shipping_address_id", null=True
    )
    payment_status = CharField(null=True)


class OrderItem(BaseModel):
    class Meta:
        table_name = "order_items"

    order = ForeignKeyField(Order, backref="items", column_name="order_id", null=True)
    product = ForeignKeyField(Product, backref="order_items", column_name="product_id", null=True)
    quantity = IntegerField(null=True)
    unit_price = DecimalField(max_digits=12, decimal_places=2, null=True)
    variant = ForeignKeyField(ProductVariant, backref="order_items", column_name="variant_id", null=True)


class Payment(BaseModel):
    class Meta:
        table_name = "payments"

    order = ForeignKeyField(Order, backref="payments", column_name="order_id", null=True)
    payment_method = CharField(null=True)
    payment_status = CharField(null=True)
    transaction_reference = CharField(null=True)
    amount = DecimalField(max_digits=12, decimal_places=2, null=True)
    paid_at = DateTimeField(null=True)


class Invoice(BaseModel):
    class Meta:
        table_name = "invoices"

    order = ForeignKeyField(Order, backref="invoices", column_name="order_id", null=True)
    invoice_number = CharField(null=True)
    invoice_url = TextField(null=True)
    gst_amount = DecimalField(max_digits=12, decimal_places=2, null=True)
    total_amount = DecimalField(max_digits=12, decimal_places=2, null=True)
    generated_at = DateTimeField(null=True)


class Shipment(BaseModel):
    class Meta:
        table_name = "shipments"

    order = ForeignKeyField(Order, backref="shipments", column_name="order_id", null=True)
    courier_name = CharField(null=True)
    tracking_number = CharField(null=True)
    shipment_status = CharField(null=True)
    shipped_at = DateTimeField(null=True)
    delivered_at = DateTimeField(null=True)
