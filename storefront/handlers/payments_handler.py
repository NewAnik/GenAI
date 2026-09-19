"""Payment endpoints. Payments are record-only: the authenticated POST /orders/{id}/payments
creates a pending Payment carrying an external transaction_reference; the provider-agnostic,
HMAC-signed POST /webhooks/payments later flips that payment (and its order) to paid.

The webhook signature reuses the same constant-time HMAC-SHA256 scheme as the WhatsApp
webhook (app/whatsapp/signature.py; copied into handlers/common/signature.py, see its
docstring for why)."""
from __future__ import annotations

import json
import logging

from storefront.config import get_settings
from storefront.db.database import connection
from storefront.db.repositories.payment_repo import PaymentRepository
from storefront.handlers.common.auth import get_current_user
from storefront.handlers.common.errors import NotFoundError, ValidationError
from storefront.handlers.common.http import decode_body, error_response, json_response, raw_body
from storefront.handlers.common.router import dispatch
from storefront.handlers.common.signature import verify_signature
from storefront.schemas.payment import PaymentResponse, RecordPaymentRequest, ensure_positive_amount
from storefront.services import order_service

logger = logging.getLogger(__name__)

_repo = PaymentRepository()


def _record_payment(event: dict) -> dict:
    user = get_current_user(event)
    order_id = int(event["pathParameters"]["order_id"])
    payload = decode_body(event, RecordPaymentRequest)
    try:
        ensure_positive_amount(payload.amount)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    try:
        payment_id = order_service.record_payment(
            order_id=order_id, user_id=user.id, payment_method=payload.payment_method,
            transaction_reference=payload.transaction_reference, amount=payload.amount,
        )
    except order_service.OrderNotFoundError:
        raise NotFoundError("order not found")

    payments = _repo.list_for_order(order_id)
    p = next((x for x in payments if x.id == payment_id), payments[-1])
    return json_response(201, PaymentResponse(
        id=p.id, order_id=p.order_id, payment_method=p.payment_method,
        payment_status=p.payment_status, transaction_reference=p.transaction_reference,
        amount=p.amount,
    ))


def _payment_webhook(event: dict) -> dict:
    body = raw_body(event)
    # API Gateway HTTP API lowercases every header name in the event.
    signature_header = (event.get("headers") or {}).get("x-signature-256")
    settings = get_settings()
    if not settings.payment_webhook_secret or not verify_signature(
        body, signature_header, settings.payment_webhook_secret
    ):
        logger.warning("payment_webhook_signature_failed")
        return error_response(403, "forbidden", "invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return error_response(400, "invalid_json", "invalid json")

    reference = payload.get("transaction_reference")
    if payload.get("status") != "paid" or not reference:
        # Nothing to apply — acknowledge so the gateway stops retrying.
        return json_response(200, {"status": "ignored"})

    applied = order_service.confirm_payment(settings, transaction_reference=reference)
    return json_response(200, {"status": "applied" if applied else "noop"})


ROUTES = {
    "POST /orders/{order_id}/payments": _record_payment,
    "POST /webhooks/payments": _payment_webhook,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
