from __future__ import annotations

from peewee import BooleanField, CharField, IntegerField, TextField

from db.models.base import TimestampMixin


class User(TimestampMixin):
    class Meta:
        table_name = "users"

    organization_id = IntegerField(null=True)
    first_name = CharField(null=True)
    last_name = CharField(null=True)
    email = CharField(null=True, unique=True)
    phone = CharField(null=True)
    # Legacy column from the pre-Cognito custom-JWT auth flow. Left in place (this table is
    # shared with wrapped-and-more-admin) but never written to or read by this package.
    password_hash = TextField(null=True)
    cognito_sub = CharField(null=True, unique=True)
    role = CharField(null=True)
    is_active = BooleanField(null=True)
