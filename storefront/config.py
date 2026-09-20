"""Env-driven settings for the storefront Lambdas.

DB_USER/DB_PASSWORD are fetched from Secrets Manager at cold start (cached via @lru_cache)
when DB_SECRET_ARN is set — this is what CDK wires up in production (see
infra/cdk/storefront_stack/storefront_stack.py), so rotating the secret doesn't require a
redeploy. That secret is RDS's own "manage master user password" secret, which holds only
username/password — not host/port/dbname — so DB_HOST/DB_PORT/DB_NAME are always plain
(non-secret) env vars set directly from CDK context, secret or no secret. Local dev/tests set
DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD directly (no AWS credentials needed to run tests —
see tests/storefront/conftest.py).

Only the fields auth/cart/orders/payments actually use — everything agent/whatsapp/qdrant/
tavily-specific lives in `app/config.py` and is out of scope here. JWT settings are gone
entirely: Cognito (via API Gateway's authorizer) is the identity source of truth now, so
this Lambda never verifies a token itself.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    payment_webhook_secret: str | None
    gst_rate: float
    default_warehouse_id: int | None
    # The admin app's public-read CloudFront distribution in front of its catalog-images S3
    # bucket (see GenAI/infra/cdk/admin_api_stack/admin_api_stack.py's CatalogImagesCdn) — used
    # only by the catalog function to resolve gift_box_images.image_url's relative object keys
    # into full URLs. None for any function that doesn't set CATALOG_IMAGES_CDN_DOMAIN.
    catalog_images_cdn_domain: str | None
    app_env: str
    log_level: str


def _db_login_from_secret(secret_arn: str) -> tuple[str, str]:
    import boto3  # provided by the Lambda runtime; not a project dependency

    client = boto3.client("secretsmanager")
    value = client.get_secret_value(SecretId=secret_arn)
    # RDS-managed master-user secret shape: {username, password, ...}. No host/port/dbname —
    # an instance can host multiple databases, and RDS doesn't put connection endpoints here.
    creds = json.loads(value["SecretString"])
    return creds["username"], creds["password"]


def _payment_webhook_secret() -> str | None:
    secret_arn = os.environ.get("PAYMENT_WEBHOOK_SECRET_ARN")
    if secret_arn:
        import boto3

        client = boto3.client("secretsmanager")
        return client.get_secret_value(SecretId=secret_arn)["SecretString"]
    return os.environ.get("PAYMENT_WEBHOOK_SECRET")


@lru_cache
def get_settings() -> Settings:
    db_secret_arn = os.environ.get("DB_SECRET_ARN")
    if db_secret_arn:
        db_user, db_password = _db_login_from_secret(db_secret_arn)
    else:
        db_user = os.environ["DB_USER"]
        db_password = os.environ["DB_PASSWORD"]

    db_host = os.environ["DB_HOST"]
    db_port = int(os.environ.get("DB_PORT", "5432"))
    db_name = os.environ["DB_NAME"]

    default_warehouse_id_raw = os.environ.get("DEFAULT_WAREHOUSE_ID")
    return Settings(
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        payment_webhook_secret=_payment_webhook_secret(),
        gst_rate=float(os.environ.get("GST_RATE", "0.18")),
        default_warehouse_id=int(default_warehouse_id_raw) if default_warehouse_id_raw else None,
        catalog_images_cdn_domain=os.environ.get("CATALOG_IMAGES_CDN_DOMAIN"),
        app_env=os.environ.get("APP_ENV", "production"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
