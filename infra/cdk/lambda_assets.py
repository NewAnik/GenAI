"""Shared Lambda code-asset + dependencies-layer building, used by both CognitoStack and
StorefrontStack so every Lambda in the app (the Cognito post-confirmation trigger and the
per-resource API handlers) runs the same storefront/ source and the same pinned dependencies,
built once.

Function code and dependencies are two separate assets on purpose: `storefront/requirements.txt`
(in particular `psycopg2-binary`'s native extension) changes far less often than the handler
source does, so keeping it in its own Lambda Layer means a source-only code change re-uploads
a few KB of Python instead of the whole dependency tree, and every function shares one copy of
the layer instead of duplicating those dependencies into each function's own package.

Requires Docker at synth/deploy time for `build_dependencies_layer` only: it's bundled inside
a Lambda-runtime container, which `psycopg2-binary`'s native extension needs regardless of the
host machine's OS. `build_storefront_code` is plain source with no native deps, so it needs no
Docker step.
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import BundlingOptions
from aws_cdk import aws_lambda as _lambda
from constructs import Construct

_CDK_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _CDK_ROOT.parent.parent
STOREFRONT_ENTRY = _REPO_ROOT / "storefront"
ADMIN_ENTRY = _REPO_ROOT / "admin_api"
LAMBDA_RUNTIME = _lambda.Runtime.PYTHON_3_12


def parse_handler(handler_spec: str) -> str:
    """"storefront/handlers/auth_handler.lambda_handler" -> "handlers.auth_handler.lambda_handler"
    (or "admin_api/handlers/..." for the admin API) — the module path is relative to the code
    asset root, so the leading top-level segment is stripped and the rest becomes dotted, as the
    generic `aws_lambda.Function` handler string requires."""
    module_path, handler_name = handler_spec.rsplit(".", 1)
    relative_module_path = module_path.split("/", 1)[1]
    return f"{relative_module_path.replace('/', '.')}.{handler_name}"


def build_storefront_code() -> _lambda.Code:
    """The storefront/ source tree as a plain (non-bundled) Lambda code asset — dependencies
    live in the Layer from `build_dependencies_layer` instead, so this needs no Docker step."""
    return _lambda.Code.from_asset(str(STOREFRONT_ENTRY))


def build_admin_code() -> _lambda.Code:
    """The admin_api/ source tree as a plain (non-bundled) Lambda code asset — same rationale as
    build_storefront_code(), for the admin API's own independent handler tree."""
    return _lambda.Code.from_asset(str(ADMIN_ENTRY))


def build_dependencies_layer(
    scope: Construct, construct_id: str = "StorefrontDependencies", *, entry: Path = STOREFRONT_ENTRY,
) -> _lambda.LayerVersion:
    """Bundles storefront/requirements.txt into a Lambda Layer, inside a Lambda-runtime Docker
    container so psycopg2-binary's native extension targets the Lambda runtime regardless of
    host OS. Call once per stack that needs it (CDK hashes source + bundling options, so
    identical calls across stacks still only build/upload the underlying asset once — each
    call here still creates its own `AWS::Lambda::LayerVersion` resource in that stack, which
    is cheap and avoids a cross-stack reference just to share one layer).

    `exclude` scopes the asset's fingerprint down to just requirements.txt: CDK decides
    whether to rerun Docker bundling from the *source* input's hash, not the bundled output,
    so without this, any change anywhere under storefront/ (a handler, a model, unrelated to
    dependencies at all) would bust the cache and rerun `pip install` in Docker on every
    synth/deploy."""
    layer_code = _lambda.Code.from_asset(
        str(entry),
        exclude=["**", "!requirements.txt"],
        bundling=BundlingOptions(
            image=LAMBDA_RUNTIME.bundling_image,
            # "python/" is the layer directory Lambda puts on PYTHONPATH for every Python
            # runtime version, unlike the versioned "python/lib/pythonX.Y/site-packages/" form.
            command=["bash", "-c", "pip install -r requirements.txt -t /asset-output/python"],
        ),
    )
    return _lambda.LayerVersion(
        scope, construct_id,
        code=layer_code,
        compatible_runtimes=[LAMBDA_RUNTIME],
        description=f"{entry.name}/requirements.txt dependencies",
    )


def build_admin_dependencies_layer(
    scope: Construct, construct_id: str = "AdminApiDependencies",
) -> _lambda.LayerVersion:
    """Same as build_dependencies_layer, pinned to admin_api/'s own requirements.txt."""
    return build_dependencies_layer(scope, construct_id, entry=ADMIN_ENTRY)
