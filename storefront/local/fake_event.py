"""Builds a synthetic API Gateway REST API (v1) proxy-integration event — the direct
replacement for httpx.AsyncClient/ASGITransport in tests, and for local dev invocation
(see run_local.py).

`route_key` keeps its old "METHOD /resource/template" shape (e.g. "POST /cart/items") for
caller convenience/backwards compatibility with existing call sites — it's split here into
the separate `httpMethod` + `resource` fields a real REST API event carries, which
`storefront.handlers.common.router.dispatch` rejoins the same way to look up the route."""
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
    _, resource = route_key.split(" ", 1)
    headers = headers or {}
    return {
        "httpMethod": method,
        "resource": resource,
        "path": path,
        # Unlike HTTP API (v2), REST API does not normalize header-name casing — preserve
        # whatever casing the caller passed in.
        "headers": headers,
        "multiValueHeaders": {k: [v] for k, v in headers.items()},
        "pathParameters": path_parameters or {},
        "requestContext": {
            "httpMethod": method,
            "resourcePath": resource,
            "authorizer": {"claims": claims} if claims is not None else {},
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
