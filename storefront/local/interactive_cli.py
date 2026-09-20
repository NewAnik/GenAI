"""Interactive, menu-driven local tester for the storefront Lambda APIs — pick a route, get
prompted for whatever it needs (identity, path params, JSON body), and see the real response,
without hand-writing event JSON or curl calls. Builds on the same build_event() helper
run_local.py uses; unlike run_local.py (one-shot, scriptable) this is a REPL for exploring the
API interactively.

Must be run with storefront/ as cwd — every import under storefront/ (handlers/, services/,
db/, local/) is bare (`from config import ...`, `from db.database import ...`), so storefront/
itself has to be the import root:

    cd storefront
    python -m local.interactive_cli

storefront/db/database.py builds its Postgres connection pool at *module import time* from
config.get_settings(), so DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD must already be in
os.environ before the first `handlers.*`/`services.*`/`db.*` import happens anywhere in this
process. To respect that ordering, every such import in this file is deferred inside a
function body, called only after ensure_env_ready() has run in main(). Only local.fake_event
and schemas.* are safe to import at module scope (they depend on nothing but msgspec/stdlib).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from dotenv import load_dotenv, set_key
from local.fake_event import build_event
from schemas.auth import UpdateUserRequest
from schemas.cart import AddCartItemRequest, UpdateCartItemRequest
from schemas.order import CheckoutRequest, CreateShipmentRequest
from schemas.payment import RecordPaymentRequest

ENV_FILE = Path(__file__).parent / ".env.local"
REQUIRED_DB_VARS = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
_SUGGESTED_DEFAULTS = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "corporate_gifting",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
}
# None means "leave unset if not already present" rather than a concrete default.
OPTIONAL_DEFAULTS: dict[str, str | None] = {
    "GST_RATE": "0.18",
    # Must match whatever warehouse_id seed_sample_data() uses (1) or checkout 409s.
    "DEFAULT_WAREHOUSE_ID": "1",
    "PAYMENT_WEBHOOK_SECRET": None,
    "CATALOG_IMAGES_CDN_DOMAIN": None,
}

# Flips true the moment any handlers.*/services.*/db.* module is first imported — db.database
# constructs its connection pool at that point, so DB_* edits after this are a no-op until the
# process restarts.
_db_pool_initialized = False


@dataclass(frozen=True)
class RouteSpec:
    route_key: str  # "POST /cart/items/{item_id}/update"
    module: str  # "handlers.cart_handler"
    body_schema: type | None
    path_params: tuple[str, ...]
    auth: str  # "user" | "admin" | "none" | "hmac"


ROUTES: list[RouteSpec] = [
    RouteSpec("POST /auth/me", "handlers.auth_handler", None, (), "user"),
    RouteSpec("POST /auth/me/update", "handlers.auth_handler", UpdateUserRequest, (), "user"),
    RouteSpec("POST /cart", "handlers.cart_handler", None, (), "user"),
    RouteSpec("POST /cart/items", "handlers.cart_handler", AddCartItemRequest, (), "user"),
    RouteSpec(
        "POST /cart/items/{item_id}/update", "handlers.cart_handler",
        UpdateCartItemRequest, ("item_id",), "user",
    ),
    RouteSpec(
        "POST /cart/items/{item_id}/remove", "handlers.cart_handler", None, ("item_id",), "user",
    ),
    RouteSpec("POST /cart/clear", "handlers.cart_handler", None, (), "user"),
    RouteSpec("POST /checkout", "handlers.orders_handler", CheckoutRequest, (), "user"),
    RouteSpec("POST /orders", "handlers.orders_handler", None, (), "user"),
    RouteSpec("POST /orders/{order_id}", "handlers.orders_handler", None, ("order_id",), "user"),
    RouteSpec(
        "POST /orders/{order_id}/cancel", "handlers.orders_handler", None, ("order_id",), "user",
    ),
    RouteSpec(
        "POST /orders/{order_id}/invoice", "handlers.orders_handler", None, ("order_id",), "user",
    ),
    RouteSpec(
        "POST /orders/{order_id}/shipments", "handlers.orders_handler", None, ("order_id",), "user",
    ),
    RouteSpec(
        "POST /orders/{order_id}/shipments/create", "handlers.orders_handler",
        CreateShipmentRequest, ("order_id",), "admin",
    ),
    RouteSpec(
        "POST /orders/{order_id}/payments", "handlers.payments_handler",
        RecordPaymentRequest, ("order_id",), "user",
    ),
    RouteSpec("POST /webhooks/payments", "handlers.payments_handler", None, (), "hmac"),
    RouteSpec("POST /catalog/gift-boxes", "handlers.catalog_handler", None, (), "none"),
]


@dataclass
class Session:
    sub: str = "local-dev-sub"
    email: str | None = "dev@example.com"
    groups: list[str] = field(default_factory=list)

    def claims(self) -> dict:
        claims: dict[str, Any] = {"sub": self.sub}
        if self.email:
            claims["email"] = self.email
        if self.groups:
            claims["cognito:groups"] = self.groups
        return claims


def _prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{message}{suffix}: ").strip()
    return raw or (default or "")


def _prompt_menu(options: list[tuple[str, str]]) -> str:
    print()
    for i, (_, label) in enumerate(options, start=1):
        print(f"  {i}. {label}")
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"enter a number 1-{len(options)}")


def ensure_env_ready() -> None:
    """Load storefront/local/.env.local if present (never overrides vars already set in the
    shell environment), prompt for any required DB var still missing, apply defaults for the
    optional ones. Must run exactly once, before the first deferred import anywhere below."""
    load_dotenv(ENV_FILE)
    for var in REQUIRED_DB_VARS:
        if not os.environ.get(var):
            os.environ[var] = _prompt(var, default=_SUGGESTED_DEFAULTS.get(var))
    for var, default in OPTIONAL_DEFAULTS.items():
        if default is not None:
            os.environ.setdefault(var, default)


def import_handler(module_path: str):
    global _db_pool_initialized
    import importlib

    module = importlib.import_module(module_path)
    _db_pool_initialized = True
    return module


def _audit_routes() -> list[str]:
    """Cross-check this file's ROUTES registry against each handler module's own ROUTES dict,
    so drift (a route added/removed/renamed in a handler but not mirrored here) is surfaced
    at startup instead of silently going stale."""
    by_module: dict[str, list[str]] = {}
    for spec in ROUTES:
        by_module.setdefault(spec.module, []).append(spec.route_key)

    mismatches: list[str] = []
    for module_path, expected_keys in by_module.items():
        module = import_handler(module_path)
        actual_keys = set(module.ROUTES.keys())
        expected = set(expected_keys)
        missing = actual_keys - expected
        extra = expected - actual_keys
        if missing:
            mismatches.append(f"{module_path}: handler has routes not in this CLI: {sorted(missing)}")
        if extra:
            mismatches.append(f"{module_path}: CLI lists routes the handler no longer has: {sorted(extra)}")
    return mismatches


# --- schema-guided body prompting -------------------------------------------------------

def _field_specs(schema_cls: type) -> list[tuple[str, type, str | None]]:
    """(name, base_type, constraint_hint) per field, in declaration order, unwrapping
    Annotated[...] to surface msgspec.Meta constraints as a human hint string."""
    import msgspec

    hints = get_type_hints(schema_cls, include_extras=True)
    specs: list[tuple[str, type, str | None]] = []
    for name in schema_cls.__struct_fields__:
        hint = hints[name]
        base_type = hint
        hint_text = None
        if get_origin(hint) is Annotated:
            args = get_args(hint)
            base_type = args[0]
            for meta in args[1:]:
                if isinstance(meta, msgspec.Meta):
                    parts = []
                    if meta.gt is not None:
                        parts.append(f"> {meta.gt}")
                    if meta.ge is not None:
                        parts.append(f">= {meta.ge}")
                    if meta.min_length is not None:
                        parts.append(f"min length {meta.min_length}")
                    if parts:
                        hint_text = ", ".join(parts)
        specs.append((name, base_type, hint_text))
    return specs


def _coerce(raw: str, base_type: type) -> Any:
    if base_type is int:
        return int(raw)
    if base_type is str:
        return raw
    if base_type is Decimal:
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal: {raw!r}") from exc
    raise ValueError(f"no local prompt support for field type {base_type!r}")


def prompt_struct(schema_cls: type) -> dict:
    """Prompt for each field of a msgspec.Struct request schema, retrying per-field on bad
    input, then round-trip the constructed instance through msgspec's own JSON encoder so the
    result matches exactly what decode_body() (also msgspec-based) expects on the wire."""
    import msgspec

    kwargs: dict[str, Any] = {}
    for name, base_type, hint_text in _field_specs(schema_cls):
        label = f"{name} ({base_type.__name__}{', ' + hint_text if hint_text else ''})"
        while True:
            raw = input(f"  {label}: ").strip()
            try:
                kwargs[name] = _coerce(raw, base_type)
                break
            except ValueError as exc:
                print(f"  ! {exc}")
    instance = schema_cls(**kwargs)
    return json.loads(msgspec.json.encode(instance))


# --- invoking a route --------------------------------------------------------------------

_STATUS_LABELS = {
    200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 409: "Conflict", 422: "Unprocessable Entity", 500: "Internal Server Error",
}


def build_event_for(spec: RouteSpec, session: Session) -> dict:
    method, resource = spec.route_key.split(" ", 1)
    path_params = {name: _prompt(f"{name} (path param)") for name in spec.path_params}
    body = prompt_struct(spec.body_schema) if spec.body_schema is not None else None
    claims = None if spec.auth in ("none", "hmac") else session.claims()
    if spec.auth == "admin" and "admin" not in session.groups:
        print("[warn] current identity has no 'admin' group in cognito:groups — expect 403")
    resolved_path = resource.format(**path_params) if path_params else resource
    return build_event(
        method, resolved_path, spec.route_key,
        body=body, path_parameters=path_params, claims=claims,
    )


def print_response(result: dict) -> None:
    status = result.get("statusCode")
    print(f"\n<- {status} {_STATUS_LABELS.get(status, '')}".rstrip())
    raw = result.get("body")
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw
    print(json.dumps(parsed, indent=2))


def invoke_and_print(spec: RouteSpec, event: dict) -> None:
    module = import_handler(spec.module)
    try:
        result = module.lambda_handler(event, None)
    except Exception as exc:  # last-resort net; dispatch() already catches handler exceptions
        print(f"[CLI] unhandled exception calling {spec.module}.lambda_handler: {exc!r}")
        return
    print_response(result)


def route_menu(session: Session) -> None:
    grouped: dict[str, list[RouteSpec]] = {}
    for spec in ROUTES:
        grouped.setdefault(spec.module, []).append(spec)

    flat: list[RouteSpec] = []
    options: list[tuple[str, str]] = []
    for module_path, specs in grouped.items():
        options.append(("_header", f"-- {module_path} --"))
        for spec in specs:
            flat.append(spec)
            auth_tag = {"user": "auth", "admin": "auth+admin", "none": "no auth", "hmac": "hmac"}[spec.auth]
            options.append((str(len(flat) - 1), f"{spec.route_key}  [{auth_tag}]"))

    print()
    idx = 0
    for key, label in options:
        if key == "_header":
            print(f"  {label}")
        else:
            idx += 1
            print(f"  {idx}. {label}")
    selectable = [key for key, _ in options if key != "_header"]
    while True:
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(selectable):
            spec = flat[int(selectable[int(raw) - 1])]
            break
        print(f"enter a number 1-{len(selectable)}")

    event = build_event_for(spec, session)
    invoke_and_print(spec, event)


# --- identity ------------------------------------------------------------------------------

def identity_menu(session: Session) -> None:
    choice = _prompt_menu([
        ("sub", f"Set sub (currently {session.sub!r})"),
        ("email", f"Set email (currently {session.email!r})"),
        ("toggle_admin", ("Remove" if "admin" in session.groups else "Add") + " 'admin' group"),
        ("groups", f"Set cognito:groups directly (currently {session.groups})"),
        ("back", "Back"),
    ])
    if choice == "sub":
        session.sub = _prompt("sub", default=session.sub)
    elif choice == "email":
        session.email = _prompt("email", default=session.email or "")
    elif choice == "toggle_admin":
        if "admin" in session.groups:
            session.groups.remove("admin")
        else:
            session.groups.append("admin")
    elif choice == "groups":
        raw = _prompt("comma-separated groups", default=",".join(session.groups))
        session.groups = [g.strip() for g in raw.split(",") if g.strip()]


# --- env settings ----------------------------------------------------------------------------

def env_menu() -> None:
    all_vars = REQUIRED_DB_VARS + list(OPTIONAL_DEFAULTS.keys())
    print()
    for var in all_vars:
        print(f"  {var} = {os.environ.get(var, '')!r}")
    var = _prompt("edit which var (blank to go back)", default="")
    if not var:
        return
    if var not in all_vars:
        print(f"unknown var {var!r}")
        return
    new_value = _prompt(f"new value for {var}", default=os.environ.get(var, ""))
    os.environ[var] = new_value

    if var in REQUIRED_DB_VARS and _db_pool_initialized:
        print(
            "[warn] a handler module already imported db.database, which built its "
            "connection pool from the old value — this change has no effect until you "
            "restart the CLI."
        )
    elif var not in REQUIRED_DB_VARS:
        try:
            import config
            config.get_settings.cache_clear()
        except ImportError:
            pass

    if _prompt("persist to .env.local? [y/N]", default="N").lower().startswith("y"):
        set_key(str(ENV_FILE), var, new_value)


# --- seeding ---------------------------------------------------------------------------------

def seed_sample_data() -> dict:
    """Insert one User/Product+ProductVariant/Inventory(warehouse_id=1)/Address directly via
    the Peewee models — mirrors tests/storefront/integration/conftest.py's `seed` fixture.
    Inserts rows only; table creation comes from the root alembic migrations, not from here."""
    from db.database import connection
    from db.models import Address, Inventory, Product, ProductVariant, User

    email, cognito_sub, sku = "buyer@example.com", "sub-buyer-1", "MUG-1"
    with connection():
        if User.select().where(User.cognito_sub == cognito_sub).exists():
            suffix = uuid.uuid4().hex[:8]
            email, cognito_sub, sku = f"buyer-{suffix}@example.com", f"sub-buyer-{suffix}", f"MUG-{suffix}"

        user = User.create(email=email, cognito_sub=cognito_sub, role="customer", is_active=True)
        product = Product.create(
            name="Mug", base_price=Decimal("100"), status="active", min_order_quantity=1,
        )
        variant = ProductVariant.create(product_id=product.id, sku=sku, price=Decimal("100"))
        inv = Inventory.create(warehouse_id=1, variant_id=variant.id, quantity=1, reserved_quantity=0)
        address = Address.create(
            user_id=user.id, address_type="shipping", recipient_name="Buyer",
            line1="1 Road", city="BLR", state="KA", pincode="560001",
        )
        return {
            "user_id": user.id, "cognito_sub": cognito_sub, "variant_id": variant.id,
            "address_id": address.id, "inventory_id": inv.id,
        }


def seed_menu(session: Session) -> None:
    ids = seed_sample_data()
    print(json.dumps(ids, indent=2))
    if _prompt("adopt this user's cognito_sub as your identity? [y/N]", default="N").lower().startswith("y"):
        session.sub = ids["cognito_sub"]
        session.groups = []


# --- payments webhook signer ------------------------------------------------------------------

def webhook_menu() -> None:
    spec = next(s for s in ROUTES if s.route_key == "POST /webhooks/payments")
    status = _prompt("status", default="paid")
    reference = _prompt("transaction_reference", default="TX-1")
    secret = _prompt("webhook secret", default=os.environ.get("PAYMENT_WEBHOOK_SECRET", ""))

    payload = {"status": status, "transaction_reference": reference}
    body_bytes = json.dumps(payload).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"

    event = build_event(
        "POST", "/webhooks/payments", spec.route_key,
        body=payload, headers={"X-Signature-256": header}, claims=None,
    )
    invoke_and_print(spec, event)


# --- main loop ---------------------------------------------------------------------------------

def main() -> None:
    ensure_env_ready()
    mismatches = _audit_routes()
    if mismatches:
        print("[warn] route registry drift detected:")
        for m in mismatches:
            print(f"  - {m}")

    session = Session()
    while True:
        choice = _prompt_menu([
            ("route", "Call a route"),
            ("identity", f"Switch identity (sub={session.sub!r}, groups={session.groups})"),
            ("env", "View/edit env settings"),
            ("seed", "Seed sample data"),
            ("webhook", "Sign & call the payments webhook"),
            ("quit", "Quit"),
        ])
        if choice == "route":
            route_menu(session)
        elif choice == "identity":
            identity_menu(session)
        elif choice == "env":
            env_menu()
        elif choice == "seed":
            seed_menu(session)
        elif choice == "webhook":
            webhook_menu()
        elif choice == "quit":
            break


if __name__ == "__main__":
    main()
