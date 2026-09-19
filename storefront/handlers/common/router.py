"""Minimal request dispatch for API Gateway REST API (v1) proxy-integration events — the
replacement for FastAPI's routing + automatic HTTPException handling. Each Lambda's
handler module builds a `{"METHOD /resource/template": route_fn}` dict and calls
`dispatch(event, ROUTES)`; `event["resource"]` is the exact resource path template CDK
registered (e.g. "/cart/items/{item_id}/update"), not the resolved path, so no manual
path-parsing is needed here — unlike HTTP API (v2)'s single `routeKey` field, REST API
splits this across `httpMethod` + `resource`, so dispatch rebuilds the same key shape."""
from __future__ import annotations

import logging
from typing import Callable

from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.http import error_response
from services.auth_service import AuthError, ForbiddenError

logger = logging.getLogger(__name__)

RouteHandler = Callable[[dict], dict]


def dispatch(event: dict, routes: dict[str, RouteHandler]) -> dict:
    route_key = f"{event.get('httpMethod')} {event.get('resource')}"
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
