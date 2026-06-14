"""Embedding-based similarity search over the product catalog (Qdrant).

CRITICAL: the query embedding MUST come from the same model/dimensionality as the offline
corpus embeddings (`app.jobs.embed_products`) — both read `settings.openai_embedding_model`
/ `settings.openai_embedding_dimensions` so they can never silently drift apart.
"""
from __future__ import annotations

from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.agent.state import Slots
from app.logging_setup import get_logger
from app.vectorstore.qdrant_client import search_similar
from app.vectorstore.schemas import QdrantHit

logger = get_logger(__name__)


def build_query_text(slots: Slots) -> str:
    parts: list[str] = []
    if slots.occasion:
        parts.append(f"corporate gifts for {slots.occasion}")
    if slots.theme_preferences:
        parts.append(", ".join(slots.theme_preferences) + " themed")
    parts.append("bulk corporate gifting, premium quality, suitable for employees or clients")
    return " ".join(parts)


async def embed_query(text: str, openai_client: AsyncOpenAI, model: str) -> list[float]:
    response = await openai_client.embeddings.create(model=model, input=[text])
    return response.data[0].embedding


async def run_semantic_search(query_text: str, top_k: int, qdrant_client: AsyncQdrantClient,
                              collection_name: str, openai_client: AsyncOpenAI, embedding_model: str,
                              score_threshold: float | None = None,
                              max_price_ceiling: float | None = None) -> list[QdrantHit]:
    vector = await embed_query(query_text, openai_client, embedding_model)

    payload_filter = None
    if max_price_ceiling is not None:
        payload_filter = qmodels.Filter(must=[
            qmodels.FieldCondition(key="status", match=qmodels.MatchValue(value="active")),
            qmodels.FieldCondition(key="base_price", range=qmodels.Range(lte=max_price_ceiling)),
        ])

    hits = await search_similar(qdrant_client, collection_name, vector, top_k,
                                score_threshold=score_threshold, payload_filter=payload_filter)
    logger.debug("semantic_search_done", query=query_text, hit_count=len(hits))
    return hits
