"""Catalog fields actually read by the storefront flow: price, sku, min order quantity.
Category/GiftBox*/ProductEmbedding are out of scope (not touched by any in-scope
repo/service) and intentionally not modeled here — see app/db/models/catalog.py for the
full catalog schema used by the (out-of-scope) agent/admin side."""
from __future__ import annotations

from peewee import BooleanField, CharField, DecimalField, ForeignKeyField, IntegerField, TextField

from storefront.db.models.base import CreatedAtMixin, TimestampMixin


class Product(TimestampMixin):
    class Meta:
        table_name = "products"

    name = CharField(null=True)
    description = TextField(null=True)
    brand = CharField(null=True)
    base_price = DecimalField(max_digits=12, decimal_places=2, null=True)
    min_order_quantity = IntegerField(null=True)
    is_customizable = BooleanField(null=True)
    status = CharField(null=True)


class ProductVariant(CreatedAtMixin):
    class Meta:
        table_name = "product_variants"

    product = ForeignKeyField(Product, backref="variants", column_name="product_id", null=True)
    sku = CharField(null=True, unique=True)
    color = CharField(null=True)
    size = CharField(null=True)
    price = DecimalField(max_digits=12, decimal_places=2, null=True)
