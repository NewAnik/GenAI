"""Unit tests for `build_filters_from_slots` — turning fuzzy conversational `Slots` into concrete
SQL filter bounds (budget band, category mapping, customization/MOQ constraints)."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.agent.state import Slots
from app.search.catalog_search import build_filters_from_slots

_SETTINGS = SimpleNamespace(search_budget_band_low=0.6, search_budget_band_high=1.15)


class _FakeCatalogRepo:
    def __init__(self, keyword_index: dict[str, str] | None = None):
        self._keyword_index = keyword_index or {}
        self.calls = 0

    async def load_category_keyword_index(self) -> dict[str, str]:
        self.calls += 1
        return self._keyword_index


async def test_budget_band_derived_from_per_recipient_budget():
    slots = Slots(occasion="Diwali", recipient_count=50, budget_per_recipient=Decimal("500"))

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    assert filters.min_price == Decimal("300.00")  # 500 * 0.6
    assert filters.max_price == Decimal("575.00")  # 500 * 1.15


async def test_budget_band_derived_from_total_budget_and_recipient_count():
    slots = Slots(occasion="Onboarding", recipient_count=100, total_budget=Decimal("50000"))

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    # per-recipient budget = 50000 / 100 = 500 -> same band as the explicit case
    assert filters.min_price == Decimal("300.00")
    assert filters.max_price == Decimal("575.00")


async def test_no_budget_signal_means_no_price_bounds():
    slots = Slots(occasion="Diwali", recipient_count=10)

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    assert filters.min_price is None
    assert filters.max_price is None


async def test_theme_preferences_mapped_to_matching_category_slugs_case_insensitively():
    repo = _FakeCatalogRepo({"eco-friendly": "eco-products", "tech": "tech-gadgets"})
    slots = Slots(theme_preferences=["Eco-Friendly", "Wellness"])

    filters = await build_filters_from_slots(slots, repo, _SETTINGS)

    assert filters.category_slugs == ["eco-products"]
    assert repo.calls == 1


async def test_no_theme_preferences_skips_category_lookup_entirely():
    repo = _FakeCatalogRepo({"eco-friendly": "eco-products"})
    slots = Slots(occasion="Diwali")

    filters = await build_filters_from_slots(slots, repo, _SETTINGS)

    assert filters.category_slugs is None
    assert repo.calls == 0


async def test_unmatched_theme_preferences_yield_no_category_slugs():
    repo = _FakeCatalogRepo({"eco-friendly": "eco-products"})
    slots = Slots(theme_preferences=["luxury", "premium"])

    filters = await build_filters_from_slots(slots, repo, _SETTINGS)

    assert filters.category_slugs is None


async def test_branding_needed_sets_is_customizable_true():
    slots = Slots(branding_needed=True)

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    assert filters.is_customizable is True


async def test_branding_not_mentioned_leaves_is_customizable_unset():
    slots = Slots()

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    assert filters.is_customizable is None


async def test_recipient_count_propagates_to_min_order_quantity_filter_and_gift_boxes_always_included():
    slots = Slots(recipient_count=35)

    filters = await build_filters_from_slots(slots, _FakeCatalogRepo(), _SETTINGS)

    assert filters.min_order_quantity_lte == 35
    assert filters.include_gift_boxes is True


async def test_empty_slots_produce_no_filters_beyond_defaults():
    filters = await build_filters_from_slots(Slots(), _FakeCatalogRepo(), _SETTINGS)

    assert filters.min_price is None
    assert filters.max_price is None
    assert filters.category_slugs is None
    assert filters.is_customizable is None
    assert filters.min_order_quantity_lte is None
    assert filters.include_gift_boxes is True
