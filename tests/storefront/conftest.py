"""Ensures storefront.config.get_settings() has enough environment to construct without
KeyError during test collection, even when no real Postgres is configured. The DB-backed
fixtures (which actually connect) live in tests/storefront/integration/conftest.py, gated
behind TEST_DATABASE_URL — this file only sets placeholders so importing storefront.db.*
never fails at collection time for the always-on unit tests.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def _apply_db_env(url: str | None) -> None:
    if url:
        normalized = (
            url.replace("postgresql+asyncpg", "postgresql")
            .replace("postgresql+psycopg", "postgresql")
        )
        parsed = urlparse(normalized)
        os.environ["DB_HOST"] = parsed.hostname or "localhost"
        os.environ["DB_PORT"] = str(parsed.port or 5432)
        os.environ["DB_NAME"] = (parsed.path or "/storefront_test").lstrip("/")
        os.environ["DB_USER"] = parsed.username or "postgres"
        os.environ["DB_PASSWORD"] = parsed.password or "postgres"
    else:
        os.environ.setdefault("DB_HOST", "localhost")
        os.environ.setdefault("DB_PORT", "5432")
        os.environ.setdefault("DB_NAME", "storefront_test_placeholder")
        os.environ.setdefault("DB_USER", "postgres")
        os.environ.setdefault("DB_PASSWORD", "postgres")


_apply_db_env(TEST_DATABASE_URL)
