"""The generic resource Lambda backing `/resources/{table}/...` — a thin HTTP-shape adapter over
services/resource_service.py, which owns authorization, SQL generation, and error translation.
See resource_service.py's module docstring and db/query_builder.py's injection-discipline note
for the design this sits on top of."""
from __future__ import annotations

from db.connection import connection
from handlers.common.auth import get_claims
from handlers.common.http import decode_json_body, json_response, path_param
from handlers.common.router import dispatch
from services import resource_service


def _list(event: dict) -> dict:
    table = path_param(event, "table")
    result = resource_service.list_resource(table, get_claims(event), decode_json_body(event))
    return json_response(200, result)


def _detail(event: dict) -> dict:
    table = path_param(event, "table")
    body = decode_json_body(event)
    result = resource_service.detail_resource(table, get_claims(event), body["id"])
    return json_response(200, result)


def _related(event: dict) -> dict:
    table = path_param(event, "table")
    result = resource_service.related_resource(table, get_claims(event), decode_json_body(event))
    return json_response(200, result)


def _lookup(event: dict) -> dict:
    table = path_param(event, "table")
    result = resource_service.lookup_resource(table, get_claims(event), decode_json_body(event))
    return json_response(200, result)


def _create(event: dict) -> dict:
    table = path_param(event, "table")
    result = resource_service.create_resource(table, get_claims(event), decode_json_body(event))
    return json_response(201, result)


def _update(event: dict) -> dict:
    table = path_param(event, "table")
    record_id = path_param(event, "id")
    result = resource_service.update_resource(table, get_claims(event), record_id, decode_json_body(event))
    return json_response(200, result)


def _delete(event: dict) -> dict:
    table = path_param(event, "table")
    record_id = path_param(event, "id")
    resource_service.delete_resource(table, get_claims(event), record_id)
    return json_response(200, {"ok": True})


ROUTES = {
    "POST /resources/{table}/list": _list,
    "POST /resources/{table}/detail": _detail,
    "POST /resources/{table}/related": _related,
    "POST /resources/{table}/lookup": _lookup,
    "POST /resources/{table}/create": _create,
    "POST /resources/{table}/{id}/update": _update,
    "POST /resources/{table}/{id}/delete": _delete,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES, context)
