from __future__ import annotations

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField

from db.models.base import BaseModel
from db.models.users import User


class AuditLog(BaseModel):
    class Meta:
        table_name = "audit_logs"

    entity_type = CharField(null=True)
    entity_id = IntegerField(null=True)
    action = CharField(null=True)
    performed_by = ForeignKeyField(User, column_name="performed_by", null=True)
    created_at = DateTimeField(null=True)
