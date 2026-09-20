"""The declared-column `type:` values config/resources.yml uses, and the SQL cast each one binds
with — see query_builder.py's module docstring. Casting explicitly (`%s::integer`, not a bare
`%s`) matters because filter/range values arrive from JSON over the wire (numbers, strings,
booleans) rather than as native Python types matching the target column, and psycopg2 infers a
bound parameter's Postgres type from the *Python* value it's given, not from the column it will be
compared against."""
from __future__ import annotations

from typing import Literal

from psycopg2 import sql

ColumnType = Literal[
    "text", "integer", "numeric", "boolean", "timestamp", "date", "uuid", "jsonb", "text_array",
]

_CAST_SQL: dict[str, str] = {
    "text": "",
    "integer": "::integer",
    "numeric": "::numeric",
    "boolean": "::boolean",
    "timestamp": "::timestamptz",
    "date": "::date",
    "uuid": "::uuid",
    "jsonb": "::jsonb",
    "text_array": "::text[]",
}


def cast_for(column_type: str) -> sql.Composable:
    return sql.SQL(_CAST_SQL.get(column_type, ""))


def array_cast_for(column_type: str) -> sql.Composable:
    """Same as cast_for, but for `= ANY(%s::<type>[])` — psycopg2 adapts a Python list to a
    Postgres array automatically, but `ANY()` still needs an explicit element type when the
    column isn't `text` (an untyped array literal defaults to `unknown[]`, which `= ANY()`
    can't compare against an integer/numeric/etc. column)."""
    suffix = _CAST_SQL.get(column_type, "")
    return sql.SQL(f"{suffix}[]") if suffix else sql.SQL("")
