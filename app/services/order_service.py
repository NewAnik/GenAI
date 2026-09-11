"""Order orchestration: the atomic checkout, cancellation (reservation release), and
shipment/fulfillment. Every mutation runs inside a single `get_session()` transaction, so
either the whole operation commits or it fully rolls back — the guarantee that keeps stock
reservations and order rows consistent under concurrency.

Stock safety comes from `InventoryRepository.lock_for_variant`, which issues
`SELECT ... FOR UPDATE`: concurrent checkouts for the same variant serialize on that row,
so two orders can never both reserve the last unit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.config import Settings
from app.db.models import (
    AuditLog,
    Invoice,
    Order,
    OrderItem,
    Payment,
    Shipment,
)
from app.db.repositories.cart_repo import CartRepository
from app.db.repositories.inventory_repo import InventoryRepository
from app.db.repositories.order_repo import OrderRepository
from app.db.repositories.payment_repo import PaymentRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_session
from app.logging_setup import get_logger
from app.services import inventory_service

logger = get_logger(__name__)

# Order statuses that still hold a live inventory reservation (cancellable, stock releasable).
_RESERVED_STATUSES = {"pending", "paid", "confirmed"}


class OrderError(Exception):
    """Base for checkout/cancel failures the API maps to 4xx responses."""


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


async def checkout(settings: Settings, *, user_id: int, org_id: int | None,
                   shipping_address_id: int) -> CheckoutResult:
    """Turn the user's active cart into a placed order, atomically reserving stock.

    Raises EmptyCartError, InvalidAddressError, or inventory_service.InsufficientStockError;
    any of these roll back the whole transaction leaving no partial order/reservation.
    """
    async with get_session() as db:
        cart_repo = CartRepository(db)
        inv_repo = InventoryRepository(db)
        order_repo = OrderRepository(db)
        user_repo = UserRepository(db)

        cart = await cart_repo.get_or_create_active(user_id)
        if not cart.items:
            raise EmptyCartError("cart is empty")

        address = await user_repo.get_address(shipping_address_id, user_id=user_id)
        if address is None:
            raise InvalidAddressError("shipping address not found for this user")

        # Reserve stock for every line first (each lock held until commit); if any line is
        # short, InsufficientStockError propagates and the transaction rolls back.
        gst_rate = Decimal(str(settings.gst_rate))
        subtotal = Decimal("0")
        planned_items: list[tuple[int, int, int, Decimal]] = []  # variant_id, product_id, qty, unit_price
        for item in cart.items:
            variant = item.variant
            quantity = item.quantity or 0
            unit_price = item.unit_price_snapshot or (variant.price if variant else None) or Decimal("0")

            inv = await inv_repo.lock_for_variant(
                item.variant_id, warehouse_id=settings.default_warehouse_id
            )
            if inv is None:
                raise inventory_service.InsufficientStockError(item.variant_id, quantity, 0)
            inventory_service.reserve(inv, quantity)

            product_id = variant.product_id if variant else None
            subtotal += unit_price * quantity
            planned_items.append((item.variant_id, product_id, quantity, unit_price))

        gst_amount = (subtotal * gst_rate).quantize(Decimal("0.01"))
        total_amount = (subtotal + gst_amount).quantize(Decimal("0.01"))

        order = Order(
            organization_id=org_id,
            user_id=user_id,
            shipping_address_id=shipping_address_id,
            status="pending",
            payment_status="pending",
            total_amount=total_amount,
        )
        order_repo.add(order)
        await order_repo.flush()  # assign order.id
        order.order_number = _order_number(order.id)

        for variant_id, product_id, quantity, unit_price in planned_items:
            db.add(OrderItem(
                order_id=order.id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                unit_price=unit_price,
            ))

        invoice = Invoice(
            order_id=order.id,
            invoice_number=_invoice_number(order.id),
            gst_amount=gst_amount,
            total_amount=total_amount,
        )
        order_repo.add_invoice(invoice)

        db.add(_audit(order.id, "order_created", None, {
            "order_number": order.order_number,
            "total_amount": str(total_amount),
            "user_id": user_id,
        }, performed_by=user_id))

        await cart_repo.mark_checked_out(cart)

        logger.info("order_created", order_id=order.id, order_number=order.order_number,
                    total_amount=str(total_amount), item_count=len(planned_items))
        return CheckoutResult(order_id=order.id, order_number=order.order_number,
                              total_amount=total_amount)
    # get_session() commits here on clean exit.


async def cancel_order(*, order_id: int, user_id: int) -> None:
    """Cancel a still-reserved order and release its inventory. Idempotent: cancelling an
    already-cancelled order is a no-op (no double-release)."""
    async with get_session() as db:
        order_repo = OrderRepository(db)
        inv_repo = InventoryRepository(db)

        order = await order_repo.get_for_user(order_id, user_id=user_id)
        if order is None:
            raise OrderNotFoundError("order not found")
        if order.status == "cancelled":
            return  # idempotent
        if order.status not in _RESERVED_STATUSES:
            raise OrderNotCancellableError(f"order in status '{order.status}' cannot be cancelled")

        for item in await order_repo.get_items(order_id):
            if item.variant_id is None:
                continue
            inv = await inv_repo.lock_for_variant(item.variant_id)
            if inv is not None:
                inventory_service.release(inv, item.quantity or 0)

        prev_status = order.status
        order.status = "cancelled"
        db.add(_audit(order.id, "order_cancelled", {"status": prev_status},
                      {"status": "cancelled"}, performed_by=user_id))
        logger.info("order_cancelled", order_id=order_id)


async def record_shipment(*, order_id: int, courier_name: str, tracking_number: str) -> int:
    """Admin fulfillment: create a shipment and convert each line's reservation into an
    actual stock decrement. Runs in one transaction."""
    async with get_session() as db:
        order_repo = OrderRepository(db)
        inv_repo = InventoryRepository(db)

        order = await order_repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError("order not found")

        for item in await order_repo.get_items(order_id):
            if item.variant_id is None:
                continue
            inv = await inv_repo.lock_for_variant(item.variant_id)
            if inv is not None:
                inventory_service.fulfill(inv, item.quantity or 0)

        shipment = Shipment(
            order_id=order_id,
            courier_name=courier_name,
            tracking_number=tracking_number,
            shipment_status="shipped",
            shipped_at=_now(),
        )
        order_repo.add_shipment(shipment)
        order.status = "shipped"
        await order_repo.flush()
        logger.info("shipment_recorded", order_id=order_id, tracking_number=tracking_number)
        return shipment.id


async def record_payment(*, order_id: int, user_id: int, payment_method: str,
                         transaction_reference: str, amount: Decimal) -> int:
    """Create a pending Payment row against the user's order. The order is later flipped to
    paid by the signed payment webhook (see confirm_payment)."""
    async with get_session() as db:
        order_repo = OrderRepository(db)
        payment_repo = PaymentRepository(db)

        order = await order_repo.get_for_user(order_id, user_id=user_id)
        if order is None:
            raise OrderNotFoundError("order not found")

        existing = await payment_repo.get_by_reference(transaction_reference)
        if existing is not None:
            return existing.id  # idempotent on reference

        payment = Payment(
            order_id=order_id,
            payment_method=payment_method,
            payment_status="pending",
            transaction_reference=transaction_reference,
            amount=amount,
        )
        payment_repo.add(payment)
        await payment_repo.flush()
        logger.info("payment_recorded", order_id=order_id, ref=transaction_reference)
        return payment.id


async def confirm_payment(settings: Settings, *, transaction_reference: str) -> bool:
    """Mark a recorded payment (and its order) paid. Idempotent on transaction_reference:
    replaying the same webhook flips the status only once. Returns True if this call
    performed the transition, False if it was already paid / reference unknown."""
    async with get_session() as db:
        payment_repo = PaymentRepository(db)
        order_repo = OrderRepository(db)

        payment = await payment_repo.get_by_reference(transaction_reference)
        if payment is None:
            logger.warning("payment_webhook_unknown_reference", ref=transaction_reference)
            return False
        if payment.payment_status == "paid":
            return False  # already applied

        payment.payment_status = "paid"
        payment.paid_at = _now()

        if payment.order_id is not None:
            order = await order_repo.get_by_id(payment.order_id)
            if order is not None:
                order.payment_status = "paid"
                if order.status == "pending":
                    order.status = "confirmed"
                db.add(_audit(order.id, "payment_confirmed", None,
                              {"transaction_reference": transaction_reference}, performed_by=None))
        logger.info("payment_confirmed", ref=transaction_reference, order_id=payment.order_id)
        return True


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _order_number(order_id: int) -> str:
    return f"ORD{_now():%Y}{order_id:06d}"


def _invoice_number(order_id: int) -> str:
    return f"INV{_now():%Y}{order_id:06d}"


def _audit(entity_id: int, action: str, old: dict | None, new: dict | None,
           *, performed_by: int | None) -> AuditLog:
    return AuditLog(entity_type="order", entity_id=entity_id, action=action,
                    old_value=old, new_value=new, performed_by=performed_by)
