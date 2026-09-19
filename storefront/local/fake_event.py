"""Builds a synthetic API Gateway HTTP API (payload format v2) event — the direct
replacement for httpx.AsyncClient/ASGITransport in tests, and for local dev invocation
(see run_local.py)."""
from __future__ import annotations

import json
from typing import Any


def build_event(
    method: str,
    path: str,
    route_key: str,
    *,
    body: Any = None,
    headers: dict | None = None,
    path_parameters: dict | None = None,
    claims: dict | None = None,
) -> dict:
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "headers": {k.lower(): v for k, v in (headers or {}).items()},
        "pathParameters": path_parameters or {},
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": claims}} if claims is not None else {},
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
