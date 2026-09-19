"""Only `Inventory` is in scope (stock reservation for checkout). `Warehouse` isn't queried
by any in-scope repo/service, so `warehouse_id` is modeled as a bare int, not a full FK —
the DB-level FK constraint already exists regardless of whether the ORM models it."""
from __future__ import annotations

from peewee import DateTimeField, ForeignKeyField, IntegerField

from storefront.db.models.base import BaseModel
from storefront.db.models.catalog import ProductVariant


class Inventory(BaseModel):
    class Meta:
        table_name = "inventory"

    warehouse_id = IntegerField(null=True)
    variant = ForeignKeyField(ProductVariant, backref="inventory_rows", column_name="variant_id", null=True)
    quantity = IntegerField(null=True)
    reserved_quantity = IntegerField(null=True)
    updated_at = DateTimeField(null=True)
