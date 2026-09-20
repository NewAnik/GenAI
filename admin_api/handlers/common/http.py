"""API Gateway REST API (v1) proxy-integration request/response helpers, backed by msgspec —
copied verbatim from storefront/handlers/common/http.py."""
from __future__ import annotations

import base64
from typing import Any, TypeVar

import msgspec
from handlers.common.errors import ValidationError

T = TypeVar("T")


def json_response(status_code: int, body: Any) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json", "access-control-allow-origin": "*"},
        "body": msgspec.json.encode(body).decode("utf-8"),
    }


def error_response(status_code: int, code: str, message: str) -> dict:
    return json_response(status_code, {"error": {"code": code, "message": message}})


def get_header(event: dict, name: str) -> str | None:
    headers = event.get("headers") or {}
    name_lower = name.lower()
    return next((v for k, v in headers.items() if k.lower() == name_lower), None)


def raw_body(event: dict) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8") if isinstance(body, str) else body


def decode_body[T](event: dict, struct_type: type[T]) -> T:
    try:
        return msgspec.json.decode(raw_body(event), type=struct_type)
    except msgspec.ValidationError as exc:
        raise ValidationError(str(exc)) from exc
    except msgspec.DecodeError as exc:
        raise ValidationError(f"invalid json body: {exc}") from exc


def path_param(event: dict, name: str) -> str:
    """A `{name}` path-template segment's resolved value, e.g. `table` from
    "/resources/{table}/list". Always present when the route matched (API Gateway wouldn't have
    invoked this Lambda otherwise), so a missing value is a genuine bug, not user input to
    validate — hence the plain KeyError rather than a ValidationError."""
    return (event.get("pathParameters") or {})[name]


def decode_json_body(event: dict) -> dict:
    """A loosely-typed JSON body for the generic resource endpoints, where the shape varies by
    table (filters/columns aren't known until resources.yml is consulted) — unlike
    `decode_body`, which is for the fixed, per-endpoint msgspec Structs bespoke handlers use."""
    raw = raw_body(event)
    if not raw:
        return {}
    try:
        decoded = msgspec.json.decode(raw)
    except msgspec.DecodeError as exc:
        raise ValidationError(f"invalid json body: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValidationError("request body must be a JSON object")
    return decoded
