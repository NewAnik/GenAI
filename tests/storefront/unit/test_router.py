"""Unit tests for storefront.handlers.common.router.dispatch — specifically the REST API (v1)
route-key construction from `httpMethod` + `resource`, since that's what changed when the
storefront API switched from HTTP API (v2, single `routeKey` field) to REST API."""
from __future__ import annotations

from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.router import dispatch
from services.auth_service import AuthError, ForbiddenError


def _event(method: str, resource: str) -> dict:
    return {"httpMethod": method, "resource": resource}


def test_dispatches_to_the_route_matching_method_and_resource():
    called = {}

    def handler(event):
        called["event"] = event
        return {"statusCode": 200, "body": "ok"}

    resp = dispatch(_event("POST", "/cart/items"), {"POST /cart/items": handler})
    assert resp == {"statusCode": 200, "body": "ok"}
    assert called["event"]["resource"] == "/cart/items"


def test_unmatched_route_returns_404():
    resp = dispatch(_event("POST", "/nope"), {"POST /cart/items": lambda e: {}})
    assert resp["statusCode"] == 404


def test_auth_error_maps_to_401():
    def handler(event):
        raise AuthError("no claims")

    resp = dispatch(_event("POST", "/cart"), {"POST /cart": handler})
    assert resp["statusCode"] == 401


def test_forbidden_error_maps_to_403():
    def handler(event):
        raise ForbiddenError("not admin")

    resp = dispatch(_event("POST", "/orders/{order_id}/shipments/create"), {
        "POST /orders/{order_id}/shipments/create": handler,
    })
    assert resp["statusCode"] == 403


def test_validation_error_maps_to_422():
    def handler(event):
        raise ValidationError("bad payload")

    resp = dispatch(_event("POST", "/cart/items"), {"POST /cart/items": handler})
    assert resp["statusCode"] == 422


def test_not_found_error_maps_to_404():
    def handler(event):
        raise NotFoundError("no such order")

    resp = dispatch(_event("POST", "/orders/{order_id}"), {"POST /orders/{order_id}": handler})
    assert resp["statusCode"] == 404


def test_unhandled_exception_maps_to_500():
    def handler(event):
        raise RuntimeError("boom")

    resp = dispatch(_event("POST", "/cart"), {"POST /cart": handler})
    assert resp["statusCode"] == 500
