"""LLM escape-hatch tool: lets the model look up real catalog facts on demand instead of
guessing, when answering an ad-hoc general question (e.g. "do you have anything eco-friendly
under 300?") that the deterministic search/curation pipeline wasn't asked to handle.

Built as a *factory* — `build_catalog_lookup_tool(catalog_repo)` — because the repo is bound to
a per-turn DB session via `NodeDeps`; nodes construct the tool fresh each turn and
`bind_tools([...])` it onto the chat model for that one ad-hoc call. This keeps the tool
testable (swap in a fake repo) and avoids any global DB state.
"""
from __future__ import annotations

from decimal import Decimal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.db.repositories.catalog_repo import CatalogFilters, CatalogRepository

_MAX_RESULTS_SHOWN = 5


class CatalogLookupArgs(BaseModel):
    keywords: str | None = Field(
        None, description="Theme/category keywords to match, e.g. 'eco-friendly', 'tech', 'wellness'")
    max_price: float | None = Field(None, description="Upper price bound per unit, in INR")
    min_price: float | None = Field(None, description="Lower price bound per unit, in INR")
    customizable_only: bool = Field(False, description="True if the user specifically wants brandable/customizable items")


def build_catalog_lookup_tool(catalog_repo: CatalogRepository) -> StructuredTool:
    async def _lookup(keywords: str | None = None, max_price: float | None = None,
                      min_price: float | None = None, customizable_only: bool = False) -> str:
        category_slugs = None
        if keywords:
            index = await catalog_repo.load_category_keyword_index()
            matched = {slug for kw, slug in index.items() if kw.lower() in keywords.lower()}
            category_slugs = sorted(matched) or None

        filters = CatalogFilters(
            min_price=Decimal(str(min_price)) if min_price is not None else None,
            max_price=Decimal(str(max_price)) if max_price is not None else None,
            category_slugs=category_slugs,
            is_customizable=True if customizable_only else None,
        )
        hits = await catalog_repo.search_by_filters(filters, limit=_MAX_RESULTS_SHOWN)
        if not hits:
            return "No matching catalog items found for those criteria."

        lines = [f"- \"{h.name}\" (₹{h.price}, {h.category_name or 'uncategorized'})" for h in hits]
        return "Matching catalog items:\n" + "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_lookup,
        name="lookup_catalog_items",
        description=(
            "Search our real product catalog for items matching keywords/budget. Use this to "
            "ground answers about what we actually stock — never invent product names or prices."
        ),
        args_schema=CatalogLookupArgs,
    )
