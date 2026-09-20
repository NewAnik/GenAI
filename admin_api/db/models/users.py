"""Peewee model for the `users` table shared with wrapped-and-more-admin and the storefront
package — see db/models/base.py for the TimestampMixin this inherits. Only the columns the admin
API's own code paths (auth, audit, staff-management, `/resources/users/...`) actually touch are
declared here; the generic resource endpoint (admin_api/services/resource_registry.py) reads/
writes `users` via raw SQL against config/resources.yml's own column list instead, so this model
is used only by auth_service.py and the bespoke handlers, not the generic CRUD path."""
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
    # Legacy column from the pre-Cognito Supabase Auth flow (see 0009_cognito_admin_auth.sql) —
    # never written to or read by this package.
    password_hash = TextField(null=True)
    cognito_sub = CharField(null=True, unique=True)
    role = CharField(null=True)
    is_active = BooleanField(null=True)
