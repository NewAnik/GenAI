"""Unit tests for functions_config.py's YAML -> FunctionConfig/RouteConfig parsing — pure
Python, no CDK synth involved."""
from __future__ import annotations

from functions_config import load_functions
from storefront_stack.storefront_stack import CONFIG_PATH


def test_loads_every_function_and_route():
    functions = load_functions(CONFIG_PATH)
    assert {fn.name for fn in functions} == {"auth", "cart", "orders", "payments"}
    total_routes = sum(len(fn.routes) for fn in functions)
    assert total_routes == 16


def test_defaults_apply_when_not_set_in_yaml():
    functions = {fn.name: fn for fn in load_functions(CONFIG_PATH)}
    auth = functions["auth"]
    assert auth.memory == 256
    assert auth.timeout == 10
    assert auth.vpc is True
    assert auth.reserved_concurrency is None


def test_webhook_route_has_no_auth():
    functions = {fn.name: fn for fn in load_functions(CONFIG_PATH)}
    webhook_routes = [r for r in functions["payments"].routes if r.path == "/webhooks/payments"]
    assert len(webhook_routes) == 1
    assert webhook_routes[0].requires_cognito is False


def test_admin_group_documented_on_shipment_create_route():
    functions = {fn.name: fn for fn in load_functions(CONFIG_PATH)}
    route = next(
        r for r in functions["orders"].routes if r.path == "/orders/{order_id}/shipments/create"
    )
    assert route.groups == ("admin",)
