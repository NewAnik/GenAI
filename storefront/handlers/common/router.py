"""Minimal request dispatch for API Gateway REST API (v1) proxy-integration events — the
replacement for FastAPI's routing + automatic HTTPException handling. Each Lambda's
handler module builds a `{"METHOD /resource/template": route_fn}` dict and calls
`dispatch(event, ROUTES)`; `event["resource"]` is the exact resource path template CDK
registered (e.g. "/cart/items/{item_id}/update"), not the resolved path, so no manual
path-parsing is needed here — unlike HTTP API (v2)'s single `routeKey` field, REST API
splits this across `httpMethod` + `resource`, so dispatch rebuilds the same key shape."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from handlers.common.auth import get_claims
from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.http import error_response
from logging_config import configure_logging
from services.auth_service import AuthError, ForbiddenError

configure_logging()

logger = logging.getLogger(__name__)

RouteHandler = Callable[[dict], dict]


def dispatch(event: dict, routes: dict[str, RouteHandler], context=None) -> dict:
    route_key = f"{event.get('httpMethod')} {event.get('resource')}"
    request_id = getattr(context, "aws_request_id", None)
    sub = get_claims(event).get("sub")
    logger.info("request_start route=%s sub=%s request_id=%s", route_key, sub, request_id)

    handler = routes.get(route_key)
    if handler is None:
        logger.warning("request_no_route route=%s request_id=%s", route_key, request_id)
        return error_response(404, "not_found", "no such route")

    start = time.monotonic()
    try:
        response = handler(event)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request_end route=%s status=%s elapsed_ms=%d request_id=%s",
            route_key, response.get("statusCode"), elapsed_ms, request_id,
        )
        return response
    except AuthError as exc:
        logger.warning(
            "request_client_error route=%s status=401 error=%s sub=%s request_id=%s",
            route_key, exc, sub, request_id,
        )
        return error_response(401, "unauthorized", str(exc))
    except ForbiddenError as exc:
        logger.warning(
            "request_client_error route=%s status=403 error=%s sub=%s request_id=%s",
            route_key, exc, sub, request_id,
        )
        return error_response(403, "forbidden", str(exc))
    except ValidationError as exc:
        logger.warning(
            "request_client_error route=%s status=422 error=%s sub=%s request_id=%s",
            route_key, exc, sub, request_id,
        )
        return error_response(422, "validation_error", str(exc))
    except NotFoundError as exc:
        logger.warning(
            "request_client_error route=%s status=404 error=%s sub=%s request_id=%s",
            route_key, exc, sub, request_id,
        )
        return error_response(404, "not_found", str(exc))
    except Exception:
        logger.exception("unhandled_error route=%s request_id=%s", route_key, request_id)
        return error_response(500, "internal_error", "internal server error")
