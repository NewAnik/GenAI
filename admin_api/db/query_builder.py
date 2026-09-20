"""Parameterized SQL builder for the generic `/resources/{table}/...` endpoints — raw psycopg2 +
`psycopg2.sql`, not peewee. Peewee needs a table's shape known at class-definition time; a truly
generic table/column/join builder in peewee means either synthesizing `Model` subclasses per
request or dropping to its low-level `Table` helper, neither of which is meaningfully safer or
simpler than composing the SQL directly here. Peewee stays the right tool for
admin_api/handlers/{dashboard,quotes,offers,campaigns}_handler.py, where the table set touched is
small and fixed.

Injection discipline (read before changing this file):
- Every identifier (table name, column name, alias) placed into SQL text is resolved *only* by
  looking up a `ResourceSpec`/`ColumnSpec`/`RelationSpec` already validated against
  services/resource_registry.py's allow-list — never a raw string taken from the request — and is
  always wrapped in `sql.Identifier(...)`. A client-sent filter/sort/search *key* is used only to
  look up the allow-listed identifier (`resource_service.py` does this lookup and raises
  ValidationError before calling anything here); it is never spliced into SQL text itself.
- Every *value* (filter value, search term, range bound, create/update payload value) is bound via
  a `%s` placeholder in the `params` list returned alongside the SQL — never string-interpolated,
  including inside an ILIKE pattern. This is what makes the class of bug PostgREST's `.or()`
  string-filter syntax needed manual comma/paren-sanitizing against (see
  wrapped-and-more-admin/src/lib/queries.ts's old `sanitiseSearch`) structurally impossible here
  rather than merely defended against: there is no string-expression channel for a filter at all.
"""
from __future__ import annotations

from psycopg2 import sql

from db.query_types import ColumnType, array_cast_for, cast_for
from services.resource_registry import ResourceSpec


class QueryError(Exception):
    """A filter/sort/search value that doesn't fit its column's declared type — the caller turns
    this into a 422, not a 500."""


def _base_from(resource: ResourceSpec) -> sql.Composable:
    return sql.Identifier(resource.table)


def _relation_join(rel) -> sql.Composable:
    return sql.SQL("LEFT JOIN {table} AS {alias} ON {base}.{local_key} = {alias}.{foreign_key}").format(
        table=sql.Identifier(rel.table),
        alias=sql.Identifier(f"rel_{rel.name}"),
        base=sql.Identifier("t"),
        local_key=sql.Identifier(rel.local_key),
        foreign_key=sql.Identifier(rel.foreign_key),
    )


def _relation_projection(rel) -> sql.Composable:
    alias = sql.Identifier(f"rel_{rel.name}")
    pairs = []
    for col in rel.columns:
        pairs.append(sql.Literal(col))
        pairs.append(sql.SQL("{alias}.{col}").format(alias=alias, col=sql.Identifier(col)))
    return sql.SQL("jsonb_build_object({pairs}) AS {name}").format(
        pairs=sql.SQL(", ").join(pairs), name=sql.Identifier(rel.name),
    )


def _select_list(resource: ResourceSpec) -> sql.Composable:
    base_cols = [
        sql.SQL("{base}.{col} AS {col}").format(base=sql.Identifier("t"), col=sql.Identifier(c.name))
        for c in resource.columns
    ]
    relation_cols = [_relation_projection(r) for r in resource.relations]
    return sql.SQL(", ").join(base_cols + relation_cols)


def _from_clause(resource: ResourceSpec) -> sql.Composable:
    joins = [_relation_join(r) for r in resource.relations]
    return sql.SQL("{table} AS t {joins}").format(
        table=_base_from(resource), joins=sql.SQL(" ").join(joins) if joins else sql.SQL(""),
    )


def _column_type(resource: ResourceSpec, column: str) -> ColumnType:
    spec = resource.column(column)
    return spec.type if spec else "text"  # type: ignore[return-value]


def build_list_query(
    resource: ResourceSpec, *, page: int, page_size: int,
    sort: tuple[str, bool] | None, search: str | None,
    filters: dict[str, object], ranges: dict[str, dict[str, object]],
) -> tuple[sql.Composable, list]:
    where_clauses: list[sql.Composable] = []
    params: list = []

    if search and resource.searchable:
        term = f"%{search}%"
        ors = []
        for col in resource.searchable:
            ors.append(sql.SQL("{base}.{col} ILIKE %s").format(base=sql.Identifier("t"), col=sql.Identifier(col)))
            params.append(term)
        where_clauses.append(sql.SQL("(") + sql.SQL(" OR ").join(ors) + sql.SQL(")"))

    for col, value in filters.items():
        if col not in resource.filterable:
            raise QueryError(f"'{col}' is not a filterable column on '{resource.name}'")
        col_type = _column_type(resource, col)
        cast = cast_for(col_type)
        if isinstance(value, list):
            # e.g. ProductDetail.tsx's stock-across-variants lookup: filters: {variant_id: [1,2,3]}.
            # `= ANY(%s)` with an explicit array cast, not a hand-built "IN (%s,%s,...)" — a
            # variable-length parameter list would otherwise mean building the placeholder count
            # from the request itself, which is exactly the kind of client-controlled SQL shape
            # this module's discipline (see the module docstring) avoids everywhere else.
            where_clauses.append(
                sql.SQL("{base}.{col} = ANY(%s{array_cast})").format(
                    base=sql.Identifier("t"), col=sql.Identifier(col), array_cast=array_cast_for(col_type),
                )
            )
            params.append(value)
        else:
            where_clauses.append(
                sql.SQL("{base}.{col} = %s{cast}").format(
                    base=sql.Identifier("t"), col=sql.Identifier(col), cast=cast,
                )
            )
            params.append(value)

    for col, bounds in ranges.items():
        if col not in resource.filterable:
            raise QueryError(f"'{col}' is not a filterable column on '{resource.name}'")
        col_type = _column_type(resource, col)
        cast = cast_for(col_type)
        from_value = bounds.get("from")
        to_value = bounds.get("to")
        if from_value is not None:
            where_clauses.append(
                sql.SQL("{base}.{col} >= %s{cast}").format(base=sql.Identifier("t"), col=sql.Identifier(col), cast=cast)
            )
            params.append(from_value)
        if to_value is not None:
            where_clauses.append(
                sql.SQL("{base}.{col} <= %s{cast}").format(base=sql.Identifier("t"), col=sql.Identifier(col), cast=cast)
            )
            params.append(to_value)

    where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_clauses) if where_clauses else sql.SQL("")

    if sort is not None:
        sort_col, ascending = sort
        if sort_col not in resource.sortable:
            raise QueryError(f"'{sort_col}' is not a sortable column on '{resource.name}'")
    elif resource.default_sort is not None:
        sort_col, ascending = resource.default_sort.column, resource.default_sort.ascending
    else:
        sort_col, ascending = resource.primary_key, False

    order_sql = sql.SQL(" ORDER BY {base}.{col} {dir} NULLS LAST").format(
        base=sql.Identifier("t"), col=sql.Identifier(sort_col),
        dir=sql.SQL("ASC" if ascending else "DESC"),
    )

    query = (
        sql.SQL("SELECT {select}, COUNT(*) OVER() AS __total_count FROM {from_clause}{where}{order}"
                " LIMIT %s OFFSET %s")
        .format(select=_select_list(resource), from_clause=_from_clause(resource), where=where_sql, order=order_sql)
    )
    params = params + [page_size, page * page_size]
    return query, params


def build_detail_query(resource: ResourceSpec, record_id: object) -> tuple[sql.Composable, list]:
    query = sql.SQL("SELECT {select} FROM {from_clause} WHERE {base}.{pk} = %s LIMIT 1").format(
        select=_select_list(resource), from_clause=_from_clause(resource),
        base=sql.Identifier("t"), pk=sql.Identifier(resource.primary_key),
    )
    return query, [record_id]


def build_lookup_query(
    resource: ResourceSpec, *, label_column: str, secondary_column: str | None,
) -> sql.Composable:
    if label_column not in [c.name for c in resource.columns]:
        raise QueryError(f"'{label_column}' is not a declared column on '{resource.name}'")
    columns = [resource.primary_key, label_column]
    if secondary_column is not None:
        if secondary_column not in [c.name for c in resource.columns]:
            raise QueryError(f"'{secondary_column}' is not a declared column on '{resource.name}'")
        columns.append(secondary_column)
    col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    return sql.SQL("SELECT {cols} FROM {table} ORDER BY {label} LIMIT 1000").format(
        cols=col_sql, table=_base_from(resource), label=sql.Identifier(label_column),
    )


def build_insert_query(resource: ResourceSpec, values: dict[str, object]) -> tuple[sql.Composable, list]:
    cols = list(values.keys())
    col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in cols)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in cols)
    query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({values}) RETURNING *").format(
        table=_base_from(resource), cols=col_sql, values=placeholders,
    )
    return query, [values[c] for c in cols]


def build_update_query(
    resource: ResourceSpec, record_id: object, values: dict[str, object],
) -> tuple[sql.Composable, list]:
    cols = list(values.keys())
    set_sql = sql.SQL(", ").join(
        sql.SQL("{col} = %s").format(col=sql.Identifier(c)) for c in cols
    )
    query = sql.SQL("UPDATE {table} SET {set_clause} WHERE {pk} = %s RETURNING *").format(
        table=_base_from(resource), set_clause=set_sql, pk=sql.Identifier(resource.primary_key),
    )
    return query, [values[c] for c in cols] + [record_id]


def build_delete_query(resource: ResourceSpec, record_id: object) -> tuple[sql.Composable, list]:
    query = sql.SQL("DELETE FROM {table} WHERE {pk} = %s").format(
        table=_base_from(resource), pk=sql.Identifier(resource.primary_key),
    )
    return query, [record_id]
