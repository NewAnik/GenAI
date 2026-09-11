"""Pure stock-reservation arithmetic over an `Inventory` row. Isolated from the DB session
so the reserve/release/fulfill invariants are unit-testable; the caller is responsible for
having row-locked the inventory row (see InventoryRepository.lock_for_variant) before
mutating it, and for committing the surrounding transaction."""
from __future__ import annotations

from app.db.models import Inventory


class InsufficientStockError(Exception):
    def __init__(self, variant_id: int | None, requested: int, available: int):
        self.variant_id = variant_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient stock for variant {variant_id}: requested {requested}, available {available}"
        )


def available(inv: Inventory) -> int:
    """Sellable units = on-hand minus already-reserved."""
    return (inv.quantity or 0) - (inv.reserved_quantity or 0)


def reserve(inv: Inventory, quantity: int) -> None:
    """Reserve `quantity` units (bumps reserved_quantity). Raises InsufficientStockError
    without mutating the row if not enough is available."""
    avail = available(inv)
    if quantity <= 0:
        raise ValueError("reserve quantity must be positive")
    if quantity > avail:
        raise InsufficientStockError(inv.variant_id, quantity, avail)
    inv.reserved_quantity = (inv.reserved_quantity or 0) + quantity


def release(inv: Inventory, quantity: int) -> None:
    """Release a previous reservation (e.g. on order cancel). Clamped at zero so a
    double-release can never drive reserved_quantity negative."""
    inv.reserved_quantity = max(0, (inv.reserved_quantity or 0) - quantity)


def fulfill(inv: Inventory, quantity: int) -> None:
    """Convert a reservation into an actual shipment: decrement both on-hand stock and the
    reservation. Both are clamped at zero for safety."""
    inv.quantity = max(0, (inv.quantity or 0) - quantity)
    inv.reserved_quantity = max(0, (inv.reserved_quantity or 0) - quantity)
