"""Enqueues an order-status notification for the separate, non-VPC notifications Lambda
(GenAI/notifications/) to pick up and email — this Lambda has no route to the public internet
(no NAT gateway on the VPC, see NetworkStack), so it can never call Resend directly itself.

The payload carries everything the consumer needs to build and send the email, since that Lambda
also has no Postgres access to look anything up."""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_QUEUE_URL_ENV = "ORDER_NOTIFICATIONS_QUEUE_URL"


def notify_order_status(*, order_id: int, order_number: str | None, new_status: str,
                         old_status: str | None, customer_email: str | None,
                         customer_name: str | None, total_amount: str,
                         changed_by_role: str) -> None:
    queue_url = os.environ.get(_QUEUE_URL_ENV)
    if not queue_url:
        logger.warning("order_notification_skipped order_id=%s reason=no_queue_url", order_id)
        return
    if not customer_email:
        logger.warning("order_notification_skipped order_id=%s reason=no_customer_email", order_id)
        return

    payload = {
        "event": "order_status_changed",
        "order_id": order_id,
        "order_number": order_number,
        "new_status": new_status,
        "old_status": old_status,
        "customer_email": customer_email,
        "customer_name": customer_name,
        "total_amount": total_amount,
        "currency": "INR",
        "changed_by_role": changed_by_role,
    }
    import boto3  # provided by the Lambda runtime; not a project dependency — see config.py

    boto3.client("sqs").send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))
