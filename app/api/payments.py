"""Payment endpoints. Payments are record-only: the authenticated `POST /orders/{id}/payments`
creates a pending Payment carrying an external `transaction_reference`; the provider-agnostic,
HMAC-signed `POST /webhooks/payments` later flips that payment (and its order) to paid.

The webhook signature reuses the same constant-time HMAC-SHA256 scheme as the WhatsApp
webhook (`app/whatsapp/signature.py`)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings_dep
from app.config import Settings
from app.db.models import User
from app.db.repositories.payment_repo import PaymentRepository
from app.logging_setup import get_logger
from app.schemas.payment import PaymentResponse, RecordPaymentRequest
from app.services import order_service
from app.whatsapp.signature import verify_signature

logger = get_logger(__name__)

router = APIRouter(tags=["payments"])


@router.post("/orders/{order_id}/payments", response_model=PaymentResponse,
             status_code=status.HTTP_201_CREATED)
async def record_payment(order_id: int, payload: RecordPaymentRequest,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> PaymentResponse:
    try:
        payment_id = await order_service.record_payment(
            order_id=order_id, user_id=user.id, payment_method=payload.payment_method,
            transaction_reference=payload.transaction_reference, amount=payload.amount,
        )
    except order_service.OrderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")

    payments = await PaymentRepository(db).list_for_order(order_id)
    p = next((x for x in payments if x.id == payment_id), payments[-1])
    return PaymentResponse(id=p.id, order_id=p.order_id, payment_method=p.payment_method,
                           payment_status=p.payment_status, transaction_reference=p.transaction_reference,
                           amount=p.amount)


@router.post("/webhooks/payments")
async def payment_webhook(request: Request, settings: Settings = Depends(get_settings_dep)):
    """Gateway callback: `{"transaction_reference": "...", "status": "paid"}` with an
    `X-Signature-256: sha256=<hmac>` header over the raw body. Idempotent on the reference."""
    raw_body = await request.body()
    signature_header = request.headers.get("X-Signature-256")

    if not settings.payment_webhook_secret or not verify_signature(
        raw_body, signature_header, settings.payment_webhook_secret
    ):
        logger.warning("payment_webhook_signature_failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid json")

    reference = payload.get("transaction_reference")
    if payload.get("status") != "paid" or not reference:
        # Nothing to apply — acknowledge so the gateway stops retrying.
        return {"status": "ignored"}

    applied = await order_service.confirm_payment(settings, transaction_reference=reference)
    return {"status": "applied" if applied else "noop"}
