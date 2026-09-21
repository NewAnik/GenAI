"""Peewee connection lifecycle for Lambda.

One `PooledPostgresqlDatabase` at module scope — created once per cold start, reused across
warm invocations of the same execution environment. `max_connections=1` because each
concurrent Lambda execution environment is its own process with (at most) one live
connection; this isn't a traditional multi-connection pool the way it would be on a
long-running server. At meaningful concurrency this can approach RDS's connection limit
before Lambda's own concurrency limits do — mitigate for now with conservative reserved
concurrency per function (see infra/cdk), and consider RDS Proxy as a later, out-of-scope
follow-up.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from config import get_settings
from playhouse.pool import PooledPostgresqlDatabase

logger = logging.getLogger(__name__)

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
    """Wrap a handler's route dispatch. Route logic wraps its own mutations in
    `database.atomic()`; this context manager's `finally` is a safety net that only matters
    if an exception left a transaction open — `reuse_if_open=True` makes reconnecting on the
    next warm invocation cheap either way."""
    try:
        database.connect(reuse_if_open=True)
    except Exception:
        logger.exception("db_connect_failed")
        raise
    logger.debug("db_connected")
    try:
        yield
    finally:
        if not database.is_closed():
            database.close()
            logger.debug("db_closed")
