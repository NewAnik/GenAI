from __future__ import annotations

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField, TextField

from db.models.base import BaseModel
from db.models.catalog import ProductVariant


class Warehouse(BaseModel):
    class Meta:
        table_name = "warehouses"

    name = CharField(null=True)
    address = TextField(null=True)
    city = CharField(null=True)
    state = CharField(null=True)
    created_at = DateTimeField(null=True)


class Inventory(BaseModel):
    class Meta:
        table_name = "inventory"

    warehouse = ForeignKeyField(Warehouse, column_name="warehouse_id", null=True)
    variant = ForeignKeyField(ProductVariant, column_name="variant_id", null=True)
    quantity = IntegerField(null=True)
    reserved_quantity = IntegerField(null=True)
    updated_at = DateTimeField(null=True)
