"""Loads config/resources.yml once per cold start — the server-side mirror of
wrapped-and-more-admin/src/resources/types.ts's `ResourceConfig`. This is the single allow-list
every generic `/resources/{table}/...` request is validated against: a table, column, filter,
sort, or search key not declared here is unreachable through the API, full stop (default-deny —
see this file's `get()` and query_builder.py's discipline around it).

Composite-primary-key tables (`offer_products`, `offer_categories`) are deliberately never
declared here — they stay reachable only through admin_api/handlers/offers_handler.py's bespoke
attach/detach endpoints, matching how the frontend's OfferScopePicker already treats them
specially rather than through the generic create/update/delete hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "resources.yml"

# Column `type:` values query_builder.py knows how to bind/cast.
COLUMN_TYPES = (
    "text", "integer", "numeric", "boolean", "timestamp", "date", "uuid", "jsonb", "text_array",
)


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str = "text"
    writable: bool = False
    required: bool = False


@dataclass(frozen=True)
class RelationSpec:
    name: str
    table: str
    local_key: str
    foreign_key: str = "id"
    columns: tuple[str, ...] = ("id", "name")


@dataclass(frozen=True)
class SortSpec:
    column: str
    ascending: bool = True


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    table: str
    primary_key: str = "id"
    columns: tuple[ColumnSpec, ...] = ()
    relations: tuple[RelationSpec, ...] = ()
    searchable: tuple[str, ...] = ()
    filterable: tuple[str, ...] = ()
    sortable: tuple[str, ...] = ()
    default_sort: SortSpec | None = None
    read_groups: tuple[str, ...] = ()
    create_groups: tuple[str, ...] = ()
    update_groups: tuple[str, ...] = ()
    delete_groups: tuple[str, ...] = ()
    audited: bool = False

    def column(self, name: str) -> ColumnSpec | None:
        return next((c for c in self.columns if c.name == name), None)

    def relation(self, name: str) -> RelationSpec | None:
        return next((r for r in self.relations if r.name == name), None)

    def groups_for(self, operation: str) -> tuple[str, ...]:
        return getattr(self, f"{operation}_groups")


def _parse_column(raw: dict) -> ColumnSpec:
    return ColumnSpec(
        name=raw["name"],
        type=raw.get("type", "text"),
        writable=raw.get("writable", False),
        required=raw.get("required", False),
    )


def _parse_relation(raw: dict) -> RelationSpec:
    return RelationSpec(
        name=raw["name"],
        table=raw["table"],
        local_key=raw["local_key"],
        foreign_key=raw.get("foreign_key", "id"),
        columns=tuple(raw.get("columns", ["id", "name"])),
    )


def _parse_sort(raw: dict | None) -> SortSpec | None:
    if raw is None:
        return None
    return SortSpec(column=raw["column"], ascending=raw.get("ascending", True))


def _parse_resource(name: str, raw: dict) -> ResourceSpec:
    return ResourceSpec(
        name=name,
        table=raw.get("table", name),
        primary_key=raw.get("primary_key", "id"),
        columns=tuple(_parse_column(c) for c in raw.get("columns", [])),
        relations=tuple(_parse_relation(r) for r in raw.get("relations", [])),
        searchable=tuple(raw.get("searchable", [])),
        filterable=tuple(raw.get("filterable", [])),
        sortable=tuple(raw.get("sortable", [])),
        default_sort=_parse_sort(raw.get("default_sort")),
        read_groups=tuple(raw.get("read_groups", [])),
        create_groups=tuple(raw.get("create_groups", [])),
        update_groups=tuple(raw.get("update_groups", [])),
        delete_groups=tuple(raw.get("delete_groups", [])),
        audited=raw.get("audited", False),
    )


@lru_cache
def _load() -> dict[str, ResourceSpec]:
    raw = yaml.safe_load(_CONFIG_PATH.read_text())
    return {name: _parse_resource(name, spec) for name, spec in raw["resources"].items()}


def get(name: str) -> ResourceSpec | None:
    """None (never a raised error) for an undeclared table — the caller (resource_service.py)
    turns that into a 404, deliberately indistinguishable from any other not-found so an
    unregistered table name doesn't get confirmed/denied any more precisely than that."""
    return _load().get(name)


def all_resources() -> dict[str, ResourceSpec]:
    return dict(_load())
