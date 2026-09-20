"""Lambda for POST /quotes/{quote_id}/convert — replaces QuoteDetail.tsx's manual
compensating-delete sequence (insert order, insert order_items, on failure delete the order,
then mark the quote converted) with one real Postgres transaction. That sequence existed only
because PostgREST has no multi-statement transaction from the browser; now that writes go
through a Lambda with a direct Postgres connection, `database.atomic()` is the actual fix rather
than a workaround, so nothing is ever left half-written."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from db.connection import connection, database
from db.models.commerce import Order, OrderItem, Quote, QuoteItem
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.errors import ConflictError, NotFoundError
from handlers.common.http import json_response, path_param
from handlers.common.router import dispatch
from services import audit_service

GST_RATE = Decimal("0.18")
NOT_CONVERTIBLE_STATUSES = {"converted", "rejected", "expired"}


def _order_number() -> str:
    # Matches QuoteDetail.tsx's nextOrderNumber(): "WM-<year>-<last 4 digits of epoch ms>".
    now_ms = int(time.time() * 1000)
    year = datetime.now(timezone.utc).year
    return f"WM-{year}-{str(now_ms)[-4:]}"


def _convert(event: dict) -> dict:
    user = require_role(event, *STAFF_ROLES)
    quote_id = path_param(event, "quote_id")

    quote = Quote.get_or_none(Quote.id == quote_id)
    if quote is None:
        raise NotFoundError("no quote with that id")
    if quote.status in NOT_CONVERTIBLE_STATUSES:
        raise ConflictError(f"a quote with status '{quote.status}' cannot be converted", "not_convertible")

    items = list(QuoteItem.select().where(QuoteItem.quote == quote_id))
    subtotal = sum((Decimal(str(item.unit_price or 0)) * (item.quantity or 0) for item in items), Decimal("0"))
    tax = (subtotal * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    old_status = quote.status
    with database.atomic():
        order = Order.create(
            organization=quote.organization_id, quote=quote_id, order_number=_order_number(),
            status="confirmed", subtotal_amount=subtotal, discount_amount=Decimal("0"),
            tax_amount=tax, shipping_amount=Decimal("0"), total_amount=subtotal + tax,
        )
        for item in items:
            OrderItem.create(
                order=order.id, product=item.product_id, quantity=item.quantity, unit_price=item.unit_price,
            )
        quote.status = "converted"
        quote.save()

    audit_service.record(
        actor_user_id=user.id, entity_type="orders", entity_id=order.id, action="create",
        new_value={"order_number": order.order_number, "quote_id": quote_id, "total_amount": str(order.total_amount)},
    )
    audit_service.record(
        actor_user_id=user.id, entity_type="quotes", entity_id=quote_id, action="update",
        old_value={"status": old_status}, new_value={"status": "converted"},
    )

    return json_response(201, {
        "id": order.id, "order_number": order.order_number, "total_amount": str(order.total_amount),
    })


ROUTES = {
    "POST /quotes/{quote_id}/convert": _convert,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
