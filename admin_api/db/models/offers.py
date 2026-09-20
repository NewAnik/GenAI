"""Peewee models for offers_handler.py's match-count and composite-PK scope attach/detach
endpoints — the two operations resources.yml deliberately excludes from the generic layer
(see that file's header comment)."""
from __future__ import annotations

from peewee import CharField, CompositeKey, DateTimeField, DecimalField, IntegerField

from db.models.base import BaseModel
from db.models.catalog import Category, Product


class Offer(BaseModel):
    class Meta:
        table_name = "offers"

    name = CharField(null=True)
    status = CharField(null=True)
    applies_to = CharField(null=True)
    organization_id = IntegerField(null=True)
    discount_value = DecimalField(null=True)
    created_at = DateTimeField(null=True)


class OfferProduct(BaseModel):
    class Meta:
        table_name = "offer_products"
        primary_key = CompositeKey("offer", "product")

    offer = IntegerField(column_name="offer_id")
    product = IntegerField(column_name="product_id")


class OfferCategory(BaseModel):
    class Meta:
        table_name = "offer_categories"
        primary_key = CompositeKey("offer", "category")

    offer = IntegerField(column_name="offer_id")
    category = IntegerField(column_name="category_id")


__all__ = ["Offer", "OfferProduct", "OfferCategory", "Category", "Product"]
