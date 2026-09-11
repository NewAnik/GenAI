"""Inventory access for stock reservation. The `lock_for_variant` query uses
`SELECT ... FOR UPDATE` so concurrent checkouts serialize on the same inventory row and
cannot oversell (see app/services/inventory_service.py)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Inventory


class InventoryRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def lock_for_variant(self, variant_id: int, *, warehouse_id: int | None = None) -> Inventory | None:
        """Row-lock the inventory record for a variant and return it. When `warehouse_id`
        is given, locks that specific warehouse's row; otherwise picks the row with the
        most available stock. Must run inside an open transaction (it does, under
        `get_session()`), and the lock is held until that transaction commits/rolls back."""
        stmt = select(Inventory).where(Inventory.variant_id == variant_id)
        if warehouse_id is not None:
            stmt = stmt.where(Inventory.warehouse_id == warehouse_id)
        # Deterministic ordering so concurrent txns lock rows in the same order (also
        # surfaces the most-stocked row first when no warehouse is pinned).
        stmt = stmt.order_by(Inventory.warehouse_id).with_for_update()

        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        if not rows:
            return None
        if warehouse_id is not None:
            return rows[0]
        # No warehouse pinned: choose the one with the most available (unreserved) stock.
        return max(rows, key=_available)


def _available(inv: Inventory) -> int:
    return (inv.quantity or 0) - (inv.reserved_quantity or 0)
