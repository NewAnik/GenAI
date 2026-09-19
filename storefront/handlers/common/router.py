"""Minimal request dispatch for API Gateway HTTP API (payload format v2) events — the
replacement for FastAPI's routing + automatic HTTPException handling. Each Lambda's
handler module builds a `{routeKey: route_fn}` dict and calls `dispatch(event, ROUTES)`;
`routeKey` (e.g. "POST /cart/items") is the exact route template CDK registered, not the
resolved path, so no manual path-parsing is needed here."""
from __future__ import annotations

import logging
from typing import Callable

from storefront.handlers.common.errors import NotFoundError, ValidationError
from storefront.handlers.common.http import error_response
from storefront.services.auth_service import AuthError, ForbiddenError

logger = logging.getLogger(__name__)

RouteHandler = Callable[[dict], dict]


def dispatch(event: dict, routes: dict[str, RouteHandler]) -> dict:
    route_key = event.get("routeKey")
    handler = routes.get(route_key)
    if handler is None:
        return error_response(404, "not_found", "no such route")
    try:
        return handler(event)
    except AuthError as exc:
        return error_response(401, "unauthorized", str(exc))
    except ForbiddenError as exc:
        return error_response(403, "forbidden", str(exc))
    except ValidationError as exc:
        return error_response(422, "validation_error", str(exc))
    except NotFoundError as exc:
        return error_response(404, "not_found", str(exc))
    except Exception:
        logger.exception("unhandled_error route=%s", route_key)
        return error_response(500, "internal_error", "internal server error")
