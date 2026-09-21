"""Env-driven settings for the admin API Lambdas — parallel to storefront/config.py, minus the
storefront-only GST/webhook fields (see that file's docstring for why DB_USER/DB_PASSWORD come
from Secrets Manager at cold start when DB_SECRET_ARN is set, and why DB_HOST/DB_PORT/DB_NAME are
always plain env vars either way)."""
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
    catalog_images_bucket: str | None
    app_env: str
    log_level: str
    log_sql: bool


def _db_login_from_secret(secret_arn: str) -> tuple[str, str]:
    import boto3  # provided by the Lambda runtime; not a project dependency

    client = boto3.client("secretsmanager")
    value = client.get_secret_value(SecretId=secret_arn)
    creds = json.loads(value["SecretString"])
    return creds["username"], creds["password"]


@lru_cache
def get_settings() -> Settings:
    db_secret_arn = os.environ.get("DB_SECRET_ARN")
    if db_secret_arn:
        db_user, db_password = _db_login_from_secret(db_secret_arn)
    else:
        db_user = os.environ["DB_USER"]
        db_password = os.environ["DB_PASSWORD"]

    return Settings(
        db_host=os.environ["DB_HOST"],
        db_port=int(os.environ.get("DB_PORT", "5432")),
        db_name=os.environ["DB_NAME"],
        db_user=db_user,
        db_password=db_password,
        catalog_images_bucket=os.environ.get("CATALOG_IMAGES_BUCKET"),
        app_env=os.environ.get("APP_ENV", "production"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        log_sql=os.environ.get("LOG_SQL", "false").lower() == "true",
    )
