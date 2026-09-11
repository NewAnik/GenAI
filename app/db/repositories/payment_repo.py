"""Payment access. Payments are record-only: rows carry an external
`transaction_reference`; a signed webhook later flips their status to paid."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    def add(self, payment: Payment) -> None:
        self._session.add(payment)

    async def flush(self) -> None:
        await self._session.flush()

    async def get_by_reference(self, transaction_reference: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.transaction_reference == transaction_reference)
        )
        return result.scalars().first()

    async def list_for_order(self, order_id: int) -> list[Payment]:
        result = await self._session.execute(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.id)
        )
        return list(result.scalars().all())
