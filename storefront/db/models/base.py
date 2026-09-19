"""Peewee base model + timestamp mixins, mirroring app/db/base.py's SQLAlchemy
TimestampMixin/CreatedAtMixin for the same `timestamp without time zone` columns.

Peewee has no `onupdate=` hook the way SQLAlchemy does. TimestampMixin.save() sets
`updated_at` in Python on every UPDATE (checked via `self._pk is not None` — None on the
initial INSERT, so that path is left to Postgres's own `server_default now()`, same as
today). Any model that inherits TimestampMixin gets this automatically; no need to
remember it per-repository.
"""
from __future__ import annotations

from datetime import datetime, timezone

from peewee import DateTimeField, Model

from storefront.db.database import database


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
