"""Cold-start logging setup for the storefront Lambdas.

Lambda's Python runtime pre-attaches its own handler to the root logger before user code
runs, so a plain `logging.basicConfig(level=...)` is a no-op without `force=True` — this is
what makes `LOG_LEVEL` actually take effect in production, not just locally.

Peewee already logs every executed query (verbatim, including bound params) via its own
`peewee` logger whenever that logger is enabled for DEBUG — see `Database._log_query` in
peewee.py. That's gated independently via `LOG_SQL` rather than tied to `LOG_LEVEL`, since
query params can carry the same customer PII that keeps this codebase from logging request/
response bodies — it's meant to be flipped on temporarily while debugging, not left on.
"""
from __future__ import annotations

import logging

from config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger("peewee").setLevel(logging.DEBUG if settings.log_sql else logging.WARNING)
