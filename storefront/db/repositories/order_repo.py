"""Order / order-item / invoice / shipment access for the storefront."""
from __future__ import annotations

from db.models import Invoice, Order, OrderItem, Shipment


class OrderRepository:
    def list_for_user(self, user_id: int, *, limit: int = 50) -> list[Order]:
        return list(
            Order.select()
            .where(Order.user == user_id)
            .order_by(Order.id.desc())
            .limit(limit)
        )

    def get_for_user(self, order_id: int, *, user_id: int) -> Order | None:
        return Order.get_or_none(Order.id == order_id, Order.user == user_id)

    def get_by_id(self, order_id: int) -> Order | None:
        return Order.get_or_none(Order.id == order_id)

    def get_items(self, order_id: int) -> list[OrderItem]:
        return list(OrderItem.select().where(OrderItem.order == order_id))

    def get_invoice(self, order_id: int) -> Invoice | None:
        return Invoice.select().where(Invoice.order_id == order_id).first()

    def get_shipments(self, order_id: int) -> list[Shipment]:
        return list(Shipment.select().where(Shipment.order_id == order_id).order_by(Shipment.id))
