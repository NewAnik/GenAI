"""Unit tests for the pure stock-reservation arithmetic that underpins atomic checkout.
No DB connection involved — an `Inventory` instance is just an attribute holder here."""
from __future__ import annotations

import pytest

from storefront.db.models import Inventory
from storefront.services import inventory_service
from storefront.services.inventory_service import InsufficientStockError


def _inv(quantity: int, reserved: int = 0, variant_id: int = 1) -> Inventory:
    return Inventory(variant_id=variant_id, quantity=quantity, reserved_quantity=reserved)


def test_available_is_on_hand_minus_reserved():
    assert inventory_service.available(_inv(10, 3)) == 7


def test_available_treats_none_counters_as_zero():
    inv = Inventory(variant_id=1, quantity=None, reserved_quantity=None)
    assert inventory_service.available(inv) == 0


def test_reserve_increments_reserved_quantity():
    inv = _inv(10, 2)
    inventory_service.reserve(inv, 3)
    assert inv.reserved_quantity == 5


def test_reserve_up_to_exactly_available_succeeds():
    inv = _inv(10, 2)  # available = 8
    inventory_service.reserve(inv, 8)
    assert inv.reserved_quantity == 10


def test_reserve_beyond_available_raises_and_does_not_mutate():
    inv = _inv(10, 8)  # available = 2
    with pytest.raises(InsufficientStockError) as excinfo:
        inventory_service.reserve(inv, 3)
    assert excinfo.value.requested == 3
    assert excinfo.value.available == 2
    assert inv.reserved_quantity == 8  # unchanged — no partial reservation


def test_reserve_non_positive_quantity_is_rejected():
    with pytest.raises(ValueError):
        inventory_service.reserve(_inv(10), 0)


def test_release_decrements_and_never_goes_negative():
    inv = _inv(10, 3)
    inventory_service.release(inv, 2)
    assert inv.reserved_quantity == 1
    inventory_service.release(inv, 5)  # over-release
    assert inv.reserved_quantity == 0  # clamped


def test_fulfill_decrements_both_on_hand_and_reserved():
    inv = _inv(10, 4)
    inventory_service.fulfill(inv, 3)
    assert inv.quantity == 7
    assert inv.reserved_quantity == 1


def test_fulfill_clamps_at_zero():
    inv = _inv(2, 1)
    inventory_service.fulfill(inv, 5)
    assert inv.quantity == 0
    assert inv.reserved_quantity == 0


def test_reserve_then_release_returns_to_baseline():
    inv = _inv(10, 0)
    inventory_service.reserve(inv, 4)
    inventory_service.release(inv, 4)
    assert inv.reserved_quantity == 0
    assert inventory_service.available(inv) == 10
