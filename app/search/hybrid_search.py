"""The recommendation search orchestrator: runs structured SQL filtering and Qdrant semantic
search concurrently, merges/dedupes them, and decides — deterministically, via a threshold
rule — whether the internal catalog is thin enough to warrant a web-search fallback.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from tavily import AsyncTavilyClient

from app.agent.state import Slots
from app.config import Settings
from app.db.repositories.catalog_repo import CatalogHit, CatalogRepository
from app.logging_setup import get_logger
from app.search.catalog_search import run_structured_search
from app.search.semantic_search import build_query_text, run_semantic_search
from app.search.web_fallback import WebIdea, fetch_web_gift_ideas

logger = get_logger(__name__)


@dataclass
class HybridSearchResult:
    catalog_hits: list[CatalogHit]
    semantic_hits: list[CatalogHit]
    merged: list[CatalogHit] = field(default_factory=list)
    used_web_fallback: bool = False
    web_ideas: list[WebIdea] = field(default_factory=list)


def _merge_and_dedupe(catalog_hits: list[CatalogHit], semantic_hits: list[CatalogHit]) -> list[CatalogHit]:
    by_key: dict[tuple[str, int], CatalogHit] = {}
    for hit in catalog_hits:
        by_key[(hit.kind, hit.id)] = hit
    for hit in semantic_hits:
        key = (hit.kind, hit.id)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = hit
        else:
            by_key[key] = CatalogHit(
                kind=existing.kind, id=existing.id, name=existing.name, description=existing.description,
                price=existing.price, category_name=existing.category_name,
                is_customizable=existing.is_customizable, image_urls=existing.image_urls,
                source="both", similarity_score=hit.similarity_score,
            )
    return list(by_key.values())


def _count_strong_hits(merged: list[CatalogHit], min_similarity: float) -> int:
    return sum(
        1 for h in merged
        if h.source in ("sql_filter", "both")
        or (h.similarity_score is not None and h.similarity_score >= min_similarity)
    )


async def search_for_gifts(slots: Slots, *, catalog_repo: CatalogRepository,
                           qdrant_client: AsyncQdrantClient, openai_client: AsyncOpenAI,
                           tavily_client: AsyncTavilyClient | None, settings: Settings) -> HybridSearchResult:
    catalog_hits, semantic_hits = await asyncio.gather(
        run_structured_search(slots, catalog_repo, settings),
        _run_semantic_and_hydrate(slots, catalog_repo, qdrant_client, openai_client, settings),
    )

    merged = _merge_and_dedupe(catalog_hits, semantic_hits)
    strong_count = _count_strong_hits(merged, settings.search_min_similarity)

    used_web_fallback = strong_count < settings.search_min_catalog_results
    web_ideas: list[WebIdea] = []
    if used_web_fallback and tavily_client is not None:
        web_ideas = await fetch_web_gift_ideas(slots, tavily_client)

    logger.info("hybrid_search_done", catalog_count=len(catalog_hits), semantic_count=len(semantic_hits),
                merged_count=len(merged), strong_count=strong_count, used_web_fallback=used_web_fallback,
                web_idea_count=len(web_ideas))

    return HybridSearchResult(catalog_hits=catalog_hits, semantic_hits=semantic_hits, merged=merged,
                              used_web_fallback=used_web_fallback, web_ideas=web_ideas)


async def _run_semantic_and_hydrate(slots: Slots, catalog_repo: CatalogRepository,
                                    qdrant_client: AsyncQdrantClient, openai_client: AsyncOpenAI,
                                    settings: Settings) -> list[CatalogHit]:
    query_text = build_query_text(slots)
    max_price_ceiling = None
    budget = slots.budget_per_recipient or (
        slots.total_budget / slots.recipient_count if slots.total_budget and slots.recipient_count else None
    )
    if budget is not None:
        max_price_ceiling = float(budget) * settings.search_budget_band_high * 1.3

    qdrant_hits = await run_semantic_search(
        query_text, settings.search_top_k_semantic, qdrant_client, settings.qdrant_collection,
        openai_client, settings.openai_embedding_model,
        score_threshold=None,  # threshold applied at the merge/strong-hit stage, not here —
        max_price_ceiling=max_price_ceiling,  # so low-similarity results can still surface as weak signal
    )
    if not qdrant_hits:
        return []

    product_ids = [h.payload.product_id for h in qdrant_hits]
    score_by_id = {h.payload.product_id: h.score for h in qdrant_hits}

    hydrated = await catalog_repo.get_by_ids(product_ids)
    result = []
    for hit in hydrated:
        result.append(CatalogHit(
            kind=hit.kind, id=hit.id, name=hit.name, description=hit.description, price=hit.price,
            category_name=hit.category_name, is_customizable=hit.is_customizable, image_urls=hit.image_urls,
            source="semantic", similarity_score=score_by_id.get(hit.id),
        ))
    return result
