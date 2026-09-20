"""Typed schema for infra/config/admin_functions.yml — the function/route-level config
admin_api_stack.py reads, parallel to functions_config.py/functions.yml for the storefront.

Kept as its own small module rather than reusing FunctionConfig/RouteConfig: those carry
storefront-only fields (gst_rate, default_warehouse_id, payment_webhook_secret_arn) that have no
meaning for the admin API, and forcing them to coexist (all defaulted, all unused here) is worse
than the ~40 lines of duplication this avoids.

Route-level `groups:` here is documentation only, same as functions.yml's — the admin API's real
authorization is table/operation-scoped (see admin_api/config/resources.yml's `*_groups` lists for
the generic resource routes) or enforced inside each bespoke handler
(admin_api/handlers/common/auth.py's `require_role`), never by API Gateway itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AdminRouteConfig:
    method: str
    path: str
    auth: str = "none"
    groups: tuple[str, ...] = ()

    @property
    def requires_cognito(self) -> bool:
        return self.auth == "cognito"


@dataclass(frozen=True)
class AdminFunctionConfig:
    name: str
    handler: str
    routes: tuple[AdminRouteConfig, ...]
    memory: int = 256
    timeout: int = 10
    reserved_concurrency: int | None = None
    vpc: bool = True


def load_admin_functions(path: Path) -> list[AdminFunctionConfig]:
    raw = yaml.safe_load(path.read_text())
    return [_parse_function(name, fn) for name, fn in raw["functions"].items()]


def _parse_function(name: str, fn: dict) -> AdminFunctionConfig:
    return AdminFunctionConfig(
        name=name,
        handler=fn["handler"],
        routes=tuple(_parse_route(route) for route in fn["routes"]),
        memory=fn.get("memory", 256),
        timeout=fn.get("timeout", 10),
        reserved_concurrency=fn.get("reserved_concurrency"),
        vpc=fn.get("vpc", True),
    )


def _parse_route(route: dict) -> AdminRouteConfig:
    return AdminRouteConfig(
        method=route["method"],
        path=route["path"],
        auth=route.get("auth", "none"),
        groups=tuple(route.get("groups", [])),
    )
