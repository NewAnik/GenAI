"""Shared fixtures for DB-backed storefront integration tests.

These exercise the real transaction + row-locking path (SELECT ... FOR UPDATE) and JSONB,
so they run against a real Postgres, not SQLite. Point them at a throwaway database via:

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/storefront_test

When the env var is unset the whole module is skipped, so the default `pytest` run stays
hermetic and offline — mirroring tests/integration/conftest.py's existing pattern.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to a throwaway Postgres to run"
)


@pytest.fixture
def database():
    """Create every in-scope table fresh, drop them afterwards. Peewee autoconnects on
    first query, so no explicit connect() is needed here."""
    from db.database import database as db
    from db.models import ALL_MODELS

    db.create_tables(ALL_MODELS)
    yield db
    db.drop_tables(ALL_MODELS, cascade=True)


@pytest.fixture
def seed(database):
    """Insert a user, a catalog-ready gift box, and a shipping address. Returns the ids the
    tests need."""
    from db.models import Address, GiftBox, User

    user = User.create(
        email="buyer@example.com", cognito_sub="sub-buyer-1", role="customer", is_active=True,
    )
    gift_box = GiftBox.create(
        name="First Light", slug="first-light", collection="Diwali",
        moq=1, selling_price=Decimal("100"),
    )
    address = Address.create(
        user_id=user.id, address_type="shipping", recipient_name="Buyer",
        line1="1 Road", city="BLR", state="KA", pincode="560001",
    )
    return {
        "user_id": user.id,
        "cognito_sub": user.cognito_sub,
        "gift_box_id": gift_box.id,
        "gift_box_slug": gift_box.slug,
        "address_id": address.id,
    }
