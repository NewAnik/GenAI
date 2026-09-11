"""Order / order-item / invoice / shipment access for the storefront."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invoice, Order, OrderItem, Shipment


class OrderRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, order: Order) -> None:
        self._session.add(order)

    async def flush(self) -> None:
        await self._session.flush()

    async def list_for_user(self, user_id: int, *, limit: int = 50) -> list[Order]:
        result = await self._session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_user(self, order_id: int, *, user_id: int) -> Order | None:
        result = await self._session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, order_id: int) -> Order | None:
        result = await self._session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_items(self, order_id: int) -> list[OrderItem]:
        result = await self._session.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        return list(result.scalars().all())

    async def get_invoice(self, order_id: int) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.order_id == order_id)
        )
        return result.scalars().first()

    def add_invoice(self, invoice: Invoice) -> None:
        self._session.add(invoice)

    async def get_shipments(self, order_id: int) -> list[Shipment]:
        result = await self._session.execute(
            select(Shipment).where(Shipment.order_id == order_id).order_by(Shipment.id)
        )
        return list(result.scalars().all())

    def add_shipment(self, shipment: Shipment) -> None:
        self._session.add(shipment)
