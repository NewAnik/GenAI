"""Peewee models for the tables admin_api's bespoke handlers (dashboard, offers, quotes) touch
directly — not the full catalog schema (the generic resource endpoint reads/writes `products`,
`categories`, etc. via raw SQL against config/resources.yml instead; see resource_service.py)."""
from __future__ import annotations

from peewee import BooleanField, CharField, DecimalField, ForeignKeyField, IntegerField, TextField

from db.models.base import TimestampMixin


class Category(TimestampMixin):
    class Meta:
        table_name = "categories"

    parent_id = IntegerField(null=True)
    name = CharField(null=True)
    slug = CharField(null=True)


class Product(TimestampMixin):
    class Meta:
        table_name = "products"

    category = ForeignKeyField(Category, backref="products", column_name="category_id", null=True)
    name = CharField(null=True)
    description = TextField(null=True)
    brand = CharField(null=True)
    base_price = DecimalField(null=True)
    min_order_quantity = IntegerField(null=True)
    is_customizable = BooleanField(null=True)
    status = CharField(null=True)


class ProductVariant(TimestampMixin):
    class Meta:
        table_name = "product_variants"

    product = ForeignKeyField(Product, backref="variants", column_name="product_id", null=True)
    sku = CharField(null=True, unique=True)
    color = CharField(null=True)
    size = CharField(null=True)
    price = DecimalField(null=True)
