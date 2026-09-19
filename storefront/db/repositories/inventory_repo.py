"""Inventory access for stock reservation. `lock_for_variant` uses `SELECT ... FOR UPDATE`
so concurrent checkouts serialize on the same inventory row and cannot oversell. Must run
inside an open `database.atomic()` block; the lock is held until that transaction
commits/rolls back — the direct Peewee equivalent of the SQLAlchemy original's
`.with_for_update()`."""
from __future__ import annotations

from db.models import Inventory


class InventoryRepository:
    def lock_for_variant(self, variant_id: int, *, warehouse_id: int | None = None) -> Inventory | None:
        query = Inventory.select().where(Inventory.variant_id == variant_id)
        if warehouse_id is not None:
            query = query.where(Inventory.warehouse_id == warehouse_id)
        # Deterministic ordering so concurrent txns lock rows in the same order.
        rows = list(query.order_by(Inventory.warehouse_id).for_update())
        if not rows:
            return None
        if warehouse_id is not None:
            return rows[0]
        # No warehouse pinned: choose the one with the most available (unreserved) stock.
        return max(rows, key=_available)


def _available(inv: Inventory) -> int:
    return (inv.quantity or 0) - (inv.reserved_quantity or 0)
