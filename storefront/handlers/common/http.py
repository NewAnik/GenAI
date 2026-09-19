"""API Gateway HTTP API (payload format v2) request/response helpers, backed by msgspec —
the replacement for FastAPI's automatic request validation and `response_model=`
serialization."""
from __future__ import annotations

import base64
from typing import Any, TypeVar

import msgspec

from storefront.handlers.common.errors import ValidationError

T = TypeVar("T")


def json_response(status_code: int, body: Any) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": msgspec.json.encode(body).decode("utf-8"),
    }


def error_response(status_code: int, code: str, message: str) -> dict:
    return json_response(status_code, {"error": {"code": code, "message": message}})


def raw_body(event: dict) -> bytes:
    """The exact request body bytes, decoding base64 when API Gateway encoded it —
    needed wherever a byte-exact body matters (HMAC signature verification)."""
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8") if isinstance(body, str) else body


def decode_body(event: dict, struct_type: type[T]) -> T:
    try:
        return msgspec.json.decode(raw_body(event), type=struct_type)
    except msgspec.ValidationError as exc:
        raise ValidationError(str(exc)) from exc
    except msgspec.DecodeError as exc:
        raise ValidationError(f"invalid json body: {exc}") from exc
