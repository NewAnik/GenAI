"""AuditLog — the one JSONB-bearing table actually written by in-scope code
(order_service._audit(), called from checkout/cancel/confirm_payment)."""
from __future__ import annotations

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField
from playhouse.postgres_ext import BinaryJSONField

from db.models.base import BaseModel
from db.models.users import User


class AuditLog(BaseModel):
    class Meta:
        table_name = "audit_logs"

    entity_type = CharField(null=True)
    entity_id = IntegerField(null=True)
    action = CharField(null=True)
    old_value = BinaryJSONField(null=True)
    new_value = BinaryJSONField(null=True)
    performed_by = ForeignKeyField(User, backref="audit_logs", column_name="performed_by", null=True)
    created_at = DateTimeField(null=True)
