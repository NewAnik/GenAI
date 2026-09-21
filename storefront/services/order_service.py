"""Order orchestration: the atomic checkout, cancellation (reservation release), and
shipment/fulfillment. Every mutation runs inside a single `database.atomic()` block, so
either the whole operation commits or it fully rolls back — the guarantee that keeps stock
reservations and order rows consistent under concurrency.

`checkout()` places gift-box orders and does not reserve stock — a gift box has no inventory of
its own yet, only its raw components do, and reconciling checkout against component stock is a
deferred follow-up. `cancel_order`/`record_shipment` still carry variant-level stock release/
fulfillment via `InventoryRepository.lock_for_variant` (`SELECT ... FOR UPDATE`) for any legacy
order item that does have a `variant_id`; every gift-box order item's `variant_id` is `None`, so
those code paths are no-ops for the orders `checkout()` now creates.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from config import Settings
from db.database import database
from db.models import AuditLog, Invoice, Order, OrderItem, OrderStatusHistory, Payment, Shipment
from db.repositories.cart_repo import CartRepository
from db.repositories.inventory_repo import InventoryRepository
from db.repositories.order_repo import OrderRepository
from db.repositories.payment_repo import PaymentRepository
from db.repositories.user_repo import UserRepository
from services import inventory_service, notifications_service

logger = logging.getLogger(__name__)

# Order statuses that still hold a live inventory reservation (cancellable, stock releasable).
_RESERVED_STATUSES = {"pending", "paid", "confirmed"}


class OrderError(Exception):
    """Base for checkout/cancel failures the handler layer maps to 4xx responses."""


class EmptyCartError(OrderError):
    pass


class InvalidAddressError(OrderError):
    pass


class OrderNotFoundError(OrderError):
    pass


class OrderNotCancellableError(OrderError):
    pass


@dataclass(frozen=True)
class CheckoutResult:
    order_id: int
    order_number: str
    total_amount: Decimal


def checkout(settings: Settings, *, user_id: int, org_id: int | None,
             shipping_address_id: int) -> CheckoutResult:
    """Turn the user's active cart into a placed order.

    Cart items are gift boxes, not product variants — there's no stock reservation here (that's a
    deferred follow-up; a gift box has no inventory of its own yet, only its raw components do).

    Raises EmptyCartError or InvalidAddressError; either rolls back the whole transaction leaving
    no partial order.
    """
    cart_repo = CartRepository()
    user_repo = UserRepository()

    with database.atomic():
        cart = cart_repo.get_or_create_active(user_id)
        items = cart_repo.items_for(cart)
        if not items:
            raise EmptyCartError("cart is empty")

        address = user_repo.get_address(shipping_address_id, user_id=user_id)
        if address is None:
            raise InvalidAddressError("shipping address not found for this user")

        user = user_repo.get_by_id(user_id)

        gst_rate = Decimal(str(settings.gst_rate))
        subtotal = Decimal("0")
        planned_items: list[tuple[int | None, int, Decimal]] = []  # (gift_box_id, quantity, unit_price)
        for item in items:
            gift_box = item.gift_box
            quantity = item.quantity or 0
            unit_price = item.unit_price_snapshot or (gift_box.selling_price if gift_box else None) or Decimal("0")
            subtotal += unit_price * quantity
            planned_items.append((item.gift_box_id, quantity, unit_price))

        gst_amount = (subtotal * gst_rate).quantize(Decimal("0.01"))
        total_amount = (subtotal + gst_amount).quantize(Decimal("0.01"))

        order = Order.create(
            organization_id=org_id, user_id=user_id, shipping_address_id=shipping_address_id,
            status="pending", payment_status="pending", total_amount=total_amount,
        )
        order.order_number = _order_number(order.id)
        order.save()

        for gift_box_id, quantity, unit_price in planned_items:
            OrderItem.create(
                order_id=order.id, gift_box_id=gift_box_id,
                quantity=quantity, unit_price=unit_price,
            )

        Invoice.create(
            order_id=order.id, invoice_number=_invoice_number(order.id),
            gst_amount=gst_amount, total_amount=total_amount,
        )

        _audit(order.id, "order_created", None, {
            "order_number": order.order_number, "total_amount": str(total_amount), "user_id": user_id,
        }, performed_by=user_id)

        OrderStatusHistory.create(
            order_id=order.id, status="pending", changed_by_user_id=user_id,
            changed_by_role="customer", note="Order placed",
        )

        cart_repo.mark_checked_out(cart)

        logger.info("order_created order_id=%s order_number=%s total_amount=%s item_count=%d",
                    order.id, order.order_number, total_amount, len(planned_items))

    # Outside the transaction: an SQS hiccup must never roll back a real order.
    try:
        notifications_service.notify_order_status(
            order_id=order.id, order_number=order.order_number, new_status="pending", old_status=None,
            customer_email=user.email if user else None,
            customer_name=f"{user.first_name or ''} {user.last_name or ''}".strip() if user else None,
            total_amount=str(total_amount), changed_by_role="customer",
        )
    except Exception:
        logger.exception("order_notification_enqueue_failed order_id=%s", order.id)

    return CheckoutResult(order_id=order.id, order_number=order.order_number, total_amount=total_amount)


def cancel_order(*, order_id: int, user_id: int) -> None:
    """Cancel a still-reserved order and release its inventory. Idempotent: cancelling an
    already-cancelled order is a no-op (no double-release)."""
    order_repo = OrderRepository()
    inv_repo = InventoryRepository()

    with database.atomic():
        order = order_repo.get_for_user(order_id, user_id=user_id)
        if order is None:
            raise OrderNotFoundError("order not found")
        if order.status == "cancelled":
            return  # idempotent
        if order.status not in _RESERVED_STATUSES:
            raise OrderNotCancellableError(f"order in status '{order.status}' cannot be cancelled")

        for item in order_repo.get_items(order_id):
            if item.variant_id is None:
                continue
            inv = inv_repo.lock_for_variant(item.variant_id)
            if inv is not None:
                inventory_service.release(inv, item.quantity or 0)
                inv.save()

        prev_status = order.status
        order.status = "cancelled"
        order.save()
        _audit(order.id, "order_cancelled", {"status": prev_status},
               {"status": "cancelled"}, performed_by=user_id)
        logger.info("order_cancelled order_id=%s", order_id)


def record_shipment(*, order_id: int, courier_name: str, tracking_number: str) -> int:
    """Admin fulfillment: create a shipment and convert each line's reservation into an
    actual stock decrement. Runs in one transaction."""
    order_repo = OrderRepository()
    inv_repo = InventoryRepository()

    with database.atomic():
        order = order_repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError("order not found")

        for item in order_repo.get_items(order_id):
            if item.variant_id is None:
                continue
            inv = inv_repo.lock_for_variant(item.variant_id)
            if inv is not None:
                inventory_service.fulfill(inv, item.quantity or 0)
                inv.save()

        shipment = Shipment.create(
            order_id=order_id, courier_name=courier_name, tracking_number=tracking_number,
            shipment_status="shipped", shipped_at=_now(),
        )
        order.status = "shipped"
        order.save()
        logger.info("shipment_recorded order_id=%s tracking_number=%s", order_id, tracking_number)
        return shipment.id


def record_payment(*, order_id: int, user_id: int, payment_method: str,
                    transaction_reference: str, amount: Decimal) -> int:
    """Create a pending Payment row against the user's order. The order is later flipped to
    paid by the signed payment webhook (see confirm_payment)."""
    order_repo = OrderRepository()
    payment_repo = PaymentRepository()

    with database.atomic():
        order = order_repo.get_for_user(order_id, user_id=user_id)
        if order is None:
            raise OrderNotFoundError("order not found")

        existing = payment_repo.get_by_reference(transaction_reference)
        if existing is not None:
            return existing.id  # idempotent on reference

        payment = Payment.create(
            order_id=order_id, payment_method=payment_method, payment_status="pending",
            transaction_reference=transaction_reference, amount=amount,
        )
        logger.info("payment_recorded order_id=%s ref=%s", order_id, transaction_reference)
        return payment.id


def confirm_payment(settings: Settings, *, transaction_reference: str) -> bool:
    """Mark a recorded payment (and its order) paid. Idempotent on transaction_reference:
    replaying the same webhook flips the status only once. Returns True if this call
    performed the transition, False if it was already paid / reference unknown."""
    payment_repo = PaymentRepository()
    order_repo = OrderRepository()

    with database.atomic():
        payment = payment_repo.get_by_reference(transaction_reference)
        if payment is None:
            logger.warning("payment_webhook_unknown_reference ref=%s", transaction_reference)
            return False
        if payment.payment_status == "paid":
            return False  # already applied

        payment.payment_status = "paid"
        payment.paid_at = _now()
        payment.save()

        if payment.order_id is not None:
            order = order_repo.get_by_id(payment.order_id)
            if order is not None:
                order.payment_status = "paid"
                if order.status == "pending":
                    order.status = "confirmed"
                order.save()
                _audit(order.id, "payment_confirmed", None,
                       {"transaction_reference": transaction_reference}, performed_by=None)
        logger.info("payment_confirmed ref=%s order_id=%s", transaction_reference, payment.order_id)
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _order_number(order_id: int) -> str:
    return f"ORD{_now():%Y}{order_id:06d}"


def _invoice_number(order_id: int) -> str:
    return f"INV{_now():%Y}{order_id:06d}"


def _audit(entity_id: int, action: str, old: dict | None, new: dict | None,
           *, performed_by: int | None) -> None:
    AuditLog.create(
        entity_type="order", entity_id=entity_id, action=action,
        old_value=old, new_value=new, performed_by=performed_by,
    )
