"""Local dev loop: builds a synthetic API Gateway event and invokes a handler in-process
against a local/dev Postgres — no SAM, no container/runtime emulation. Uses the same
build_event() helper as tests/storefront, so local dev and tests exercise the same code path.

Example:
    DB_HOST=localhost DB_PORT=5432 DB_NAME=genai DB_USER=postgres DB_PASSWORD=postgres \\
        python -m storefront.local.run_local --route "POST /cart/items" \\
        --body '{"variant_id": 1, "quantity": 2}' --sub some-cognito-sub
"""
from __future__ import annotations

import argparse
import importlib
import json

from storefront.local.fake_event import build_event

_HANDLER_MODULE_BY_PREFIX = {
    "/auth": "storefront.handlers.auth_handler",
    "/cart": "storefront.handlers.cart_handler",
    "/checkout": "storefront.handlers.orders_handler",
    "/orders": "storefront.handlers.orders_handler",
    "/webhooks/payments": "storefront.handlers.payments_handler",
}


def _module_for(path: str) -> str:
    for prefix, module in _HANDLER_MODULE_BY_PREFIX.items():
        if path.startswith(prefix):
            return module
    raise SystemExit(f"no handler module mapped for path {path!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke a storefront Lambda handler locally.")
    parser.add_argument("--route", required=True, help='e.g. "POST /cart/items"')
    parser.add_argument("--body", default=None, help="JSON request body")
    parser.add_argument("--path-params", default=None, help='JSON, e.g. \'{"order_id": "1"}\'')
    parser.add_argument("--sub", default="local-dev-sub", help="Cognito sub to simulate")
    parser.add_argument("--groups", default="", help="comma-separated cognito:groups")
    args = parser.parse_args()

    method, path = args.route.split(" ", 1)
    claims = {"sub": args.sub}
    if args.groups:
        claims["cognito:groups"] = args.groups.split(",")

    event = build_event(
        method, path, args.route,
        body=json.loads(args.body) if args.body else None,
        path_parameters=json.loads(args.path_params) if args.path_params else None,
        claims=claims,
    )
    module = importlib.import_module(_module_for(path))
    result = module.lambda_handler(event, None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
