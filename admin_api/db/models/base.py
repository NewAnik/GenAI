"""Peewee base model + timestamp mixin — copied verbatim from storefront/db/models/base.py."""
from __future__ import annotations

from datetime import datetime, timezone

from db.connection import database
from peewee import DateTimeField, Model


class BaseModel(Model):
    class Meta:
        database = database


class TimestampMixin(BaseModel):
    created_at = DateTimeField(null=True)
    updated_at = DateTimeField(null=True)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return super().save(*args, **kwargs)


class CreatedAtMixin(BaseModel):
    created_at = DateTimeField(null=True)
