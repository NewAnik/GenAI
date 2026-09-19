"""Order orchestration: the atomic checkout, cancellation (reservation release), and
shipment/fulfillment. Every mutation runs inside a single `database.atomic()` block, so
either the whole operation commits or it fully rolls back — the guarantee that keeps stock
reservations and order rows consistent under concurrency.

Stock safety comes from `InventoryRepository.lock_for_variant`, which issues
`SELECT ... FOR UPDATE`: concurrent checkouts for the same variant serialize on that row,
so two orders can never both reserve the last unit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from storefront.config import Settings
from storefront.db.database import database
from storefront.db.models import AuditLog, Invoice, Order, OrderItem, Payment, Shipment
from storefront.db.repositories.cart_repo import CartRepository
from storefront.db.repositories.inventory_repo import InventoryRepository
from storefront.db.repositories.order_repo import OrderRepository
from storefront.db.repositories.payment_repo import PaymentRepository
from storefront.db.repositories.user_repo import UserRepository
from storefront.services import inventory_service

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
    """Turn the user's active cart into a placed order, atomically reserving stock.

    Raises EmptyCartError, InvalidAddressError, or inventory_service.InsufficientStockError;
    any of these roll back the whole transaction leaving no partial order/reservation.
    """
    cart_repo = CartRepository()
    inv_repo = InventoryRepository()
    order_repo = OrderRepository()
    user_repo = UserRepository()

    with database.atomic():
        cart = cart_repo.get_or_create_active(user_id)
        items = cart_repo.items_for(cart)
        if not items:
            raise EmptyCartError("cart is empty")

        address = user_repo.get_address(shipping_address_id, user_id=user_id)
        if address is None:
            raise InvalidAddressError("shipping address not found for this user")

        # Reserve stock for every line first (each lock held until commit); if any line is
        # short, InsufficientStockError propagates and the transaction rolls back.
        gst_rate = Decimal(str(settings.gst_rate))
        subtotal = Decimal("0")
        planned_items: list[tuple[int, int | None, int, Decimal]] = []
        for item in items:
            variant = item.variant
            quantity = item.quantity or 0
            unit_price = item.unit_price_snapshot or (variant.price if variant else None) or Decimal("0")

            inv = inv_repo.lock_for_variant(item.variant_id, warehouse_id=settings.default_warehouse_id)
            if inv is None:
                raise inventory_service.InsufficientStockError(item.variant_id, quantity, 0)
            inventory_service.reserve(inv, quantity)
            inv.save()

            product_id = variant.product_id if variant else None
            subtotal += unit_price * quantity
            planned_items.append((item.variant_id, product_id, quantity, unit_price))

        gst_amount = (subtotal * gst_rate).quantize(Decimal("0.01"))
        total_amount = (subtotal + gst_amount).quantize(Decimal("0.01"))

        order = Order.create(
            organization_id=org_id, user_id=user_id, shipping_address_id=shipping_address_id,
            status="pending", payment_status="pending", total_amount=total_amount,
        )
        order.order_number = _order_number(order.id)
        order.save()

        for variant_id, product_id, quantity, unit_price in planned_items:
            OrderItem.create(
                order_id=order.id, product_id=product_id, variant_id=variant_id,
                quantity=quantity, unit_price=unit_price,
            )

        Invoice.create(
            order_id=order.id, invoice_number=_invoice_number(order.id),
            gst_amount=gst_amount, total_amount=total_amount,
        )

        _audit(order.id, "order_created", None, {
            "order_number": order.order_number, "total_amount": str(total_amount), "user_id": user_id,
        }, performed_by=user_id)

        cart_repo.mark_checked_out(cart)

        logger.info("order_created order_id=%s order_number=%s total_amount=%s item_count=%d",
                    order.id, order.order_number, total_amount, len(planned_items))
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
