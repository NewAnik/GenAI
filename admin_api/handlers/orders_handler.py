"""Lambda for POST /orders/{order_id}/status — the one place order status is actually allowed to
change. Replaces wrapped-and-more-admin's old direct write via the generic
/resources/orders/{id}/update endpoint, which had no transition guard and no side effects at all.
"""
from __future__ import annotations

import json
import logging
import os

import msgspec

from db.connection import connection, database
from db.models.commerce import Order, OrderStatusHistory
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.errors import ConflictError, NotFoundError
from handlers.common.http import decode_body, json_response, path_param
from handlers.common.router import dispatch
from services import audit_service

logger = logging.getLogger(__name__)

# Mirrors wrapped-and-more-admin/src/lib/enums.ts's orderTransitions exactly. The DB CHECK
# constraint on orders.status only enforces value membership, not transition order — this is the
# actual server-side enforcement OrderTimeline.tsx's client-side graph never had.
ORDER_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("confirmed", "cancelled"),
    "confirmed": ("in_production", "cancelled"),
    "in_production": ("ready_to_ship", "cancelled"),
    "ready_to_ship": ("shipped", "cancelled"),
    "shipped": ("delivered", "returned"),
    "delivered": ("returned",),
    "cancelled": (),
    "returned": (),
}


class ChangeStatusRequest(msgspec.Struct, kw_only=True):
    status: str
    note: str | None = None


def _change_status(event: dict) -> dict:
    user = require_role(event, *STAFF_ROLES)
    order_id = path_param(event, "order_id")
    payload = decode_body(event, ChangeStatusRequest)

    order = Order.get_or_none(Order.id == order_id)
    if order is None:
        raise NotFoundError("no order with that id")

    allowed = ORDER_TRANSITIONS.get(order.status, ())
    if payload.status not in allowed:
        raise ConflictError(
            f"cannot move an order from '{order.status}' to '{payload.status}'", "invalid_transition",
        )

    old_status = order.status
    with database.atomic():
        order.status = payload.status
        order.save()
        OrderStatusHistory.create(
            order_id=order.id, status=payload.status, changed_by_user_id=user.id,
            changed_by_role="staff", note=payload.note,
        )

    audit_service.record(
        actor_user_id=user.id, entity_type="orders", entity_id=order.id, action="update",
        old_value={"status": old_status}, new_value={"status": payload.status},
    )

    try:
        _enqueue_notification(order, old_status, payload.status)
    except Exception:
        logger.exception("order_notification_enqueue_failed order_id=%s", order.id)

    return json_response(200, {"id": order.id, "status": order.status})


def _enqueue_notification(order: Order, old_status: str, new_status: str) -> None:
    queue_url = os.environ.get("ORDER_NOTIFICATIONS_QUEUE_URL")
    if not queue_url or order.user_id is None:
        return
    customer = order.user
    if customer is None or not customer.email:
        return
    payload = {
        "event": "order_status_changed",
        "order_id": order.id,
        "order_number": order.order_number,
        "new_status": new_status,
        "old_status": old_status,
        "customer_email": customer.email,
        "customer_name": f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
        "total_amount": str(order.total_amount),
        "currency": "INR",
        "changed_by_role": "staff",
    }
    import boto3  # provided by the Lambda runtime; not a project dependency — see config.py

    boto3.client("sqs").send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))


ROUTES = {
    "POST /orders/{order_id}/status": _change_status,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
