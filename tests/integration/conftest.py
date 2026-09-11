"""Shared fixtures for DB-backed order-flow integration tests.

These tests exercise the real transaction + row-locking path (SELECT ... FOR UPDATE), so
they run against a **real Postgres**, not SQLite (SQLite can't express FOR UPDATE and the
schema uses JSONB). Point them at a throwaway database via:

    TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/corp_gifting_test

When the env var is unset the whole module is skipped, so the default `pytest` run stays
hermetic and offline like the rest of the suite.
"""
from __future__ import annotations

import os
from decimal import Decimal

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to a throwaway Postgres to run"
)


@pytest_asyncio.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db.base import Base
    from app.db import models  # noqa: F401 -- register all mapped classes

    eng = create_async_engine(TEST_DATABASE_URL, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Rebind app.db.session to the test engine so get_session() (used everywhere) hits the
    test DB. Returns a factory for seeding/asserting directly."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    import app.db.session as db_session

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    db_session.engine = engine
    db_session.async_session_factory = factory
    return factory


@pytest_asyncio.fixture
async def seed(session_factory):
    """Insert a user (password 'pw'), a product+variant, a warehouse, and inventory of 1
    unit. Returns the ids the tests need."""
    from app.db.models import (
        Inventory, Product, ProductVariant, User, Warehouse, Address,
    )
    from app.services.auth_service import hash_password

    async with session_factory() as s:
        user = User(email="buyer@example.com", password_hash=hash_password("pw"),
                    role="buyer", is_active=True, organization_id=None)
        s.add(user)
        product = Product(name="Mug", base_price=Decimal("100"), status="active",
                          min_order_quantity=1)
        s.add(product)
        await s.flush()
        variant = ProductVariant(product_id=product.id, sku="MUG-1", price=Decimal("100"))
        warehouse = Warehouse(name="WH1")
        s.add_all([variant, warehouse])
        await s.flush()
        inv = Inventory(warehouse_id=warehouse.id, variant_id=variant.id,
                        quantity=1, reserved_quantity=0)
        address = Address(user_id=user.id, address_type="shipping", recipient_name="Buyer",
                          line1="1 Road", city="BLR", state="KA", pincode="560001")
        s.add_all([inv, address])
        await s.commit()
        return {
            "user_id": user.id, "variant_id": variant.id,
            "address_id": address.id, "inventory_id": inv.id,
        }


@pytest_asyncio.fixture
async def client(session_factory):
    """httpx AsyncClient bound to the FastAPI app in-process (no network)."""
    from httpx import ASGITransport, AsyncClient
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
