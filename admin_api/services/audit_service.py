"""App-level replacement for wrapped-and-more-admin's `0006_audit.sql` trigger, now that writes
go through this API instead of directly through Postgres (a DB trigger can no longer be the thing
that's always there to catch a write). Called explicitly wherever a write happens: the generic
resource_service.py write path (for any resource with `audited: true` in config/resources.yml),
and bespoke handlers that write outside it (quotes_handler.py's conversion, offers_handler.py's
scope attach/detach).

Same behavior as the old trigger: records an old/new JSON diff, strips `password_hash` from
either side (defense in depth — that column should never be in an audited resource's `columns`
list at all, per resources.yml's `users` entry, but this is a second, cheap backstop), and skips
logging when nothing meaningful changed (an update that only touched `updated_at`).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg2.extras
from db.connection import raw_connection


def _dumps(value: object) -> str:
    """`RETURNING *` hands back real Python types for a row — in particular `datetime` for
    timestamp(tz) columns — which the stdlib json encoder doesn't know how to serialize on its
    own. `default=str` (`str(datetime)`/`str(Decimal)`/etc.) is enough for an audit trail, which
    only needs to be human-readable, not round-tripped back into the same Python types."""
    return json.dumps(value, default=str)


_REDACT = {"password_hash"}
_IGNORE_ON_DIFF = {"updated_at"}


def _redact(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in _REDACT}


def _meaningfully_changed(old: dict | None, new: dict | None) -> bool:
    if old is None or new is None:
        return True
    old_diff = {k: v for k, v in old.items() if k not in _IGNORE_ON_DIFF}
    new_diff = {k: v for k, v in new.items() if k not in _IGNORE_ON_DIFF}
    return old_diff != new_diff


def record(
    *, actor_user_id: int | None, entity_type: str, entity_id: object, action: str,
    old_value: dict | None = None, new_value: dict | None = None,
) -> None:
    old_value = _redact(old_value)
    new_value = _redact(new_value)
    if action == "update" and not _meaningfully_changed(old_value, new_value):
        return

    conn = raw_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs (performed_by, entity_type, entity_id, action, "
            "old_value, new_value, created_at) VALUES (%s, %s, %s::integer, %s, %s, %s, %s)",
            (
                actor_user_id, entity_type, entity_id, action,
                psycopg2.extras.Json(old_value, dumps=_dumps) if old_value is not None else None,
                psycopg2.extras.Json(new_value, dumps=_dumps) if new_value is not None else None,
                datetime.now(timezone.utc).replace(tzinfo=None),
            ),
        )
    conn.commit()
