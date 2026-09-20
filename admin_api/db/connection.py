"""Peewee connection lifecycle for Lambda — copied verbatim from storefront/db/database.py (see
that file's docstring for why `max_connections=1` and why RDS Proxy is the known follow-up once
concurrency grows). The same Postgres database as the storefront and the WhatsApp agent — this
module only owns the admin API's own connection object, not a separate database."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from config import get_settings
from playhouse.pool import PooledPostgresqlDatabase

_settings = get_settings()

database = PooledPostgresqlDatabase(
    _settings.db_name,
    host=_settings.db_host,
    port=_settings.db_port,
    user=_settings.db_user,
    password=_settings.db_password,
    max_connections=1,
    stale_timeout=280,
)


@contextmanager
def connection() -> Iterator[None]:
    database.connect(reuse_if_open=True)
    try:
        yield
    finally:
        if not database.is_closed():
            database.close()


def raw_connection():
    """The underlying psycopg2 connection peewee's PooledPostgresqlDatabase wraps — used by
    query_builder.py's parameterized SQL, which deliberately bypasses the ORM for the generic
    resource endpoints (see query_builder.py's module docstring for why)."""
    database.connect(reuse_if_open=True)
    return database.connection()
