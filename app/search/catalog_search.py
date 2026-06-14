"""Translates collected user `Slots` into structured SQL filters and runs the catalog search."""
from __future__ import annotations

from decimal import Decimal

from app.agent.state import Slots
from app.config import Settings
from app.db.repositories.catalog_repo import CatalogFilters, CatalogHit, CatalogRepository
from app.logging_setup import get_logger

logger = get_logger(__name__)


def _per_recipient_budget(slots: Slots) -> Decimal | None:
    if slots.budget_per_recipient is not None:
        return slots.budget_per_recipient
    if slots.total_budget is not None and slots.recipient_count:
        return slots.total_budget / slots.recipient_count
    return None


async def build_filters_from_slots(slots: Slots, repo: CatalogRepository, settings: Settings) -> CatalogFilters:
    min_price = max_price = None
    budget = _per_recipient_budget(slots)
    if budget is not None:
        min_price = (budget * Decimal(str(settings.search_budget_band_low))).quantize(Decimal("0.01"))
        max_price = (budget * Decimal(str(settings.search_budget_band_high))).quantize(Decimal("0.01"))

    category_slugs: list[str] | None = None
    if slots.theme_preferences:
        keyword_index = await repo.load_category_keyword_index()
        matched = {keyword_index[k.lower()] for k in slots.theme_preferences if k.lower() in keyword_index}
        category_slugs = sorted(matched) or None

    return CatalogFilters(
        min_price=min_price,
        max_price=max_price,
        category_slugs=category_slugs,
        is_customizable=True if slots.branding_needed else None,
        min_order_quantity_lte=slots.recipient_count,
        include_gift_boxes=True,
    )


async def run_structured_search(slots: Slots, repo: CatalogRepository, settings: Settings) -> list[CatalogHit]:
    filters = await build_filters_from_slots(slots, repo, settings)
    hits = await repo.search_by_filters(filters, limit=settings.search_top_k_sql)
    logger.debug("structured_search_done", filters=filters, hit_count=len(hits))
    return hits
