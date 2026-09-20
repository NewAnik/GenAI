"""Orchestrates the generic `/resources/{table}/...` endpoints: looks up the table's
`ResourceSpec` (services/resource_registry.py), authorizes the operation, builds and runs the
parameterized SQL (db/query_builder.py), and translates Postgres constraint errors into the
`{code, message}` shape the frontend's `describeError` expects. This is the only place the
generic CRUD family's request/response shapes are defined — admin_api/handlers/resource_handler.py
is a thin HTTP-shape adapter over this module.
"""
from __future__ import annotations

import logging

import psycopg2
import psycopg2.errors
import psycopg2.extras
from db.connection import raw_connection
from db.query_builder import (
    QueryError,
    build_delete_query,
    build_detail_query,
    build_insert_query,
    build_list_query,
    build_lookup_query,
    build_update_query,
)
from handlers.common.errors import ConflictError, NotFoundError, ValidationError
from services import audit_service, resource_registry
from services.auth_service import User, require_group, resolve_staff_user

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 200


def _get_resource(table: str) -> resource_registry.ResourceSpec:
    resource = resource_registry.get(table)
    if resource is None:
        # Deliberately the same "not found" a client gets for a missing row — an unregistered
        # table name isn't confirmed or denied any more precisely than that.
        raise NotFoundError(f"no such resource '{table}'")
    return resource


def authorize(resource: resource_registry.ResourceSpec, operation: str, claims: dict) -> User:
    user = resolve_staff_user(claims)
    require_group(claims, *resource.groups_for(operation))
    return user


def _execute(query, params) -> list[dict]:
    conn = raw_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if cur.description is None:
                conn.commit()
                return []
            rows = [dict(row) for row in cur.fetchall()]
        conn.commit()
        return rows
    except psycopg2.errors.UniqueViolation as exc:
        conn.rollback()
        raise ConflictError("a record with that value already exists", "unique_violation") from exc
    except psycopg2.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise ConflictError("this record is referenced elsewhere, or references a missing row", "foreign_key_violation") from exc
    except psycopg2.errors.CheckViolation as exc:
        conn.rollback()
        raise ValidationError("value violates a database constraint", "check_violation") from exc
    except psycopg2.errors.NotNullViolation as exc:
        conn.rollback()
        raise ValidationError("a required field is missing", "not_null_violation") from exc


def _autofill_gift_box_contents(box_id) -> None:
    """Fill gift_boxes.contents_line from its linked items, but only while it's still blank —
    once an admin has customized the wording, item changes must never silently overwrite it."""
    if box_id is None:
        return
    rows = _execute("SELECT contents_line FROM gift_boxes WHERE id = %s", [box_id])
    if not rows or (rows[0]["contents_line"] or "").strip():
        return
    items = _execute(
        "SELECT gi.quantity, p.name FROM gift_box_items gi "
        "JOIN products p ON p.id = gi.product_id WHERE gi.gift_box_id = %s ORDER BY gi.id",
        [box_id],
    )
    contents_line = ", ".join(f"{item['quantity'] or 1} x {item['name']}" for item in items) or None
    _execute("UPDATE gift_boxes SET contents_line = %s WHERE id = %s", [contents_line, box_id])


def list_resource(table: str, claims: dict, body: dict) -> dict:
    resource = _get_resource(table)
    authorize(resource, "read", claims)

    page = int(body.get("page", 0))
    page_size = min(int(body.get("pageSize", _DEFAULT_PAGE_SIZE)), _MAX_PAGE_SIZE)
    sort_raw = body.get("sort")
    sort = (sort_raw["column"], sort_raw.get("ascending", True)) if sort_raw else None
    search = body.get("search") or None
    filters = body.get("filters") or {}
    ranges = body.get("ranges") or {}

    try:
        query, params = build_list_query(
            resource, page=page, page_size=page_size, sort=sort, search=search,
            filters=filters, ranges=ranges,
        )
    except QueryError as exc:
        raise ValidationError(str(exc)) from exc

    rows = _execute(query, params)
    total = rows[0]["__total_count"] if rows else 0
    for row in rows:
        row.pop("__total_count", None)
    return {"rows": rows, "total": total}


def detail_resource(table: str, claims: dict, record_id: str) -> dict:
    resource = _get_resource(table)
    authorize(resource, "read", claims)
    query, params = build_detail_query(resource, record_id)
    rows = _execute(query, params)
    if not rows:
        raise NotFoundError(f"no {table} record with that id")
    return rows[0]


def related_resource(table: str, claims: dict, body: dict) -> dict:
    """Backs useRelatedRows/ChildSpec: `table` here is the *child* resource; `foreignKey` is
    validated against the child's own filterable list, exactly like any other filter."""
    resource = _get_resource(table)
    authorize(resource, "read", claims)

    foreign_key = body["foreignKey"]
    parent_id = body["parentId"]
    if foreign_key not in resource.filterable:
        raise ValidationError(f"'{foreign_key}' is not a filterable column on '{table}'")

    sort_raw = body.get("orderBy")
    sort = (sort_raw["column"], sort_raw.get("ascending", True)) if sort_raw else None
    page_size = min(int(body.get("limit", _MAX_PAGE_SIZE)), _MAX_PAGE_SIZE)

    try:
        query, params = build_list_query(
            resource, page=0, page_size=page_size, sort=sort, search=None,
            filters={foreign_key: parent_id}, ranges={},
        )
    except QueryError as exc:
        raise ValidationError(str(exc)) from exc

    rows = _execute(query, params)
    for row in rows:
        row.pop("__total_count", None)
    return {"rows": rows}


def lookup_resource(table: str, claims: dict, body: dict) -> list[dict]:
    resource = _get_resource(table)
    authorize(resource, "read", claims)
    try:
        query = build_lookup_query(
            resource, label_column=body["labelColumn"], secondary_column=body.get("secondaryColumn"),
        )
    except QueryError as exc:
        raise ValidationError(str(exc)) from exc
    return _execute(query, [])


def _validate_write_payload(resource: resource_registry.ResourceSpec, body: dict, *, is_create: bool) -> dict:
    writable = {c.name: c for c in resource.columns if c.writable}
    unknown = set(body.keys()) - set(writable.keys())
    if unknown:
        raise ValidationError(f"unwritable/unknown field(s): {', '.join(sorted(unknown))}")
    if is_create:
        missing = [c.name for c in resource.columns if c.required and c.name not in body]
        if missing:
            raise ValidationError(f"missing required field(s): {', '.join(missing)}")
    return {k: v for k, v in body.items() if k in writable}


def create_resource(table: str, claims: dict, body: dict) -> dict:
    resource = _get_resource(table)
    user = authorize(resource, "create", claims)
    values = _validate_write_payload(resource, body, is_create=True)
    if not values:
        raise ValidationError("request body must include at least one writable field")

    query, params = build_insert_query(resource, values)
    rows = _execute(query, params)
    row = rows[0]
    if resource.audited:
        audit_service.record(
            actor_user_id=user.id, entity_type=table, entity_id=row.get(resource.primary_key),
            action="create", new_value=row,
        )
    if table == "gift_box_items":
        _autofill_gift_box_contents(row.get("gift_box_id"))
    return row


def update_resource(table: str, claims: dict, record_id: str, body: dict) -> dict:
    resource = _get_resource(table)
    user = authorize(resource, "update", claims)
    values = _validate_write_payload(resource, body, is_create=False)
    if not values:
        raise ValidationError("request body must include at least one writable field")

    old_row = detail_resource(table, claims, record_id) if resource.audited else None

    query, params = build_update_query(resource, record_id, values)
    rows = _execute(query, params)
    if not rows:
        raise NotFoundError(f"no {table} record with that id")
    row = rows[0]
    if resource.audited:
        audit_service.record(
            actor_user_id=user.id, entity_type=table, entity_id=record_id,
            action="update", old_value=old_row, new_value=row,
        )
    if table == "gift_box_items":
        _autofill_gift_box_contents(row.get("gift_box_id"))
        if old_row and old_row.get("gift_box_id") != row.get("gift_box_id"):
            _autofill_gift_box_contents(old_row.get("gift_box_id"))
    return row


def delete_resource(table: str, claims: dict, record_id: str) -> None:
    resource = _get_resource(table)
    user = authorize(resource, "delete", claims)
    old_row = detail_resource(table, claims, record_id) if resource.audited else None

    query, params = build_delete_query(resource, record_id)
    _execute(query, params)
    if resource.audited:
        audit_service.record(
            actor_user_id=user.id, entity_type=table, entity_id=record_id,
            action="delete", old_value=old_row,
        )
    if table == "gift_box_items" and old_row:
        _autofill_gift_box_contents(old_row.get("gift_box_id"))
