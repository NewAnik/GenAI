"""Catalog fields actually read by the storefront flow: price, sku, min order quantity, and (as
of the catalog-browsing endpoint — see handlers/catalog_handler.py) the gift-box models the public
site's product grid reads. Category/ProductEmbedding are still out of scope (not touched by any
in-scope repo/service) — see app/db/models/catalog.py for the full catalog schema used by the
(out-of-scope) agent/admin side."""
from __future__ import annotations

from db.models.base import BaseModel, CreatedAtMixin, TimestampMixin
from peewee import BooleanField, CharField, DecimalField, ForeignKeyField, IntegerField, TextField
from playhouse.postgres_ext import ArrayField


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


class GiftBox(BaseModel):
    """No timestamp columns on this table (unlike most others here) — gift_boxes predates the
    slug/collection/occasions/moq columns added for the public catalogue and never got them."""

    class Meta:
        table_name = "gift_boxes"

    name = CharField(null=True)
    slug = CharField(null=True, unique=True)
    collection = CharField(null=True)
    # Postgres text[] — the first real use of peewee's ArrayField in this codebase (admin_api's
    # generic resource layer handles the same column via raw SQL/psycopg2's automatic Python
    # list <-> Postgres array adaptation instead, since it has no per-table model classes).
    occasions = ArrayField(CharField, null=True)
    moq = IntegerField(null=True)
    description = TextField(null=True)
    selling_price = DecimalField(max_digits=12, decimal_places=2, null=True)


class GiftBoxItem(BaseModel):
    class Meta:
        table_name = "gift_box_items"

    gift_box = ForeignKeyField(GiftBox, backref="items", column_name="gift_box_id", null=True)
    product = ForeignKeyField(Product, column_name="product_id", null=True)
    quantity = IntegerField(null=True)


class GiftBoxImage(CreatedAtMixin):
    class Meta:
        table_name = "gift_box_images"

    gift_box = ForeignKeyField(GiftBox, backref="images", column_name="gift_box_id", null=True)
    # A relative object key ("gift-boxes/{id}/{uuid}.webp"), not a full URL — resolved into one
    # by catalog_handler.py using Settings.catalog_images_cdn_domain. See
    # admin_api/handlers/images_handler.py for where this key is minted on upload.
    image_url = CharField(null=True)
    alt_text = CharField(null=True)
    width = IntegerField(null=True)
    height = IntegerField(null=True)
    display_order = IntegerField(null=True)
