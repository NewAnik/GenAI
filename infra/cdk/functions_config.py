"""Typed schema for infra/config/functions.yml, so storefront_stack.py reads
`fn_config.memory` / `route.requires_cognito` instead of `fn_config.get("memory", 256)` /
`route.get("auth") == "cognito"`. Parsing raw YAML dicts happens once, here, in `load_functions`
— everywhere else deals only with `FunctionConfig`/`RouteConfig` attributes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RouteConfig:
    method: str
    path: str
    auth: str = "none"
    # Documentation only — see functions.yml's header comment. Group membership is enforced
    # inside the handler (storefront/handlers/common/auth.py's require_role), not here.
    groups: tuple[str, ...] = ()

    @property
    def requires_cognito(self) -> bool:
        return self.auth == "cognito"


@dataclass(frozen=True)
class FunctionConfig:
    name: str
    handler: str
    routes: tuple[RouteConfig, ...]
    memory: int = 256
    timeout: int = 10
    reserved_concurrency: int | None = None
    # See functions.yml's header comment for why this defaults to true and when to flip it.
    vpc: bool = True
    gst_rate: str = "0.18"
    default_warehouse_id: int | None = None
    payment_webhook_secret_arn: str | None = None


def load_functions(path: Path) -> list[FunctionConfig]:
    raw = yaml.safe_load(path.read_text())
    return [_parse_function(name, fn) for name, fn in raw["functions"].items()]


def _parse_function(name: str, fn: dict) -> FunctionConfig:
    return FunctionConfig(
        name=name,
        handler=fn["handler"],
        routes=tuple(_parse_route(route) for route in fn["routes"]),
        memory=fn.get("memory", 256),
        timeout=fn.get("timeout", 10),
        reserved_concurrency=fn.get("reserved_concurrency"),
        vpc=fn.get("vpc", True),
        gst_rate=str(fn.get("gst_rate", "0.18")),
        default_warehouse_id=fn.get("default_warehouse_id"),
        payment_webhook_secret_arn=fn.get("payment_webhook_secret_arn"),
    )


def _parse_route(route: dict) -> RouteConfig:
    return RouteConfig(
        method=route["method"],
        path=route["path"],
        auth=route.get("auth", "none"),
        groups=tuple(route.get("groups", [])),
    )
