"""Lambda for the order-notifications SQS queue. Deliberately outside the VPC (see
infra/cdk/notifications_stack/notifications_stack.py) — this is the one function in this repo that
needs the public internet (to call Resend) and never touches Postgres, the mirror image of every
storefront/admin_api function.

Each SQS record is a JSON payload produced by GenAI/storefront/services/notifications_service.py
or GenAI/admin_api/handlers/orders_handler.py — this Lambda has no DB access at all, so that
payload has to carry everything needed to send the email (see templates.build_email)."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import boto3
from resend_client import send_email
from templates import build_email

logger = logging.getLogger(__name__)
logging.getLogger().setLevel(os.environ.get("LOG_LEVEL", "INFO"))


@lru_cache
def _resend_api_key() -> str:
    secret_arn = os.environ["RESEND_API_KEY_SECRET_ARN"]
    client = boto3.client("secretsmanager")
    return json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])['api_key']


def lambda_handler(event: dict, context=None) -> dict:
    """Returns `batchItemFailures` for any record that failed to send, so SQS retries only
    those (see the SqsEventSource's `report_batch_item_failures=True`) instead of the whole
    batch."""
    failures = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            email = build_email(body)
            if not send_email(_resend_api_key(), email):
                raise RuntimeError(f"resend rejected email for order_id={body.get('order_id')}")
        except Exception:
            logger.exception("order_notification_failed message_id=%s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
