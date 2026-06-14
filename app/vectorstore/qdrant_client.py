"""Qdrant integration: collection lifecycle, upsert, and similarity search.

`product_embeddings.embedding_id` (Postgres) stores the *string* point ID used here — the
vectors themselves live in Qdrant, not Postgres, matching the schema's design (the table has
no inline vector column, only a reference id).
"""
from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings
from app.logging_setup import get_logger
from app.vectorstore.schemas import ProductPayload, QdrantHit

logger = get_logger(__name__)


def get_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


async def ensure_collection(client: AsyncQdrantClient, collection_name: str,
                            vector_size: int, distance: qmodels.Distance = qmodels.Distance.COSINE) -> None:
    """Idempotent collection creation — safe to call at startup and from the embeddings job."""
    exists = await client.collection_exists(collection_name)
    if exists:
        return
    await client.create_collection(
        collection_name=collection_name,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
    )
    logger.info("qdrant_collection_created", collection=collection_name, size=vector_size)


async def upsert_product_vector(client: AsyncQdrantClient, collection_name: str, point_id: str,
                                vector: list[float], payload: ProductPayload) -> None:
    await client.upsert(
        collection_name=collection_name,
        points=[qmodels.PointStruct(id=point_id, vector=vector, payload=payload.model_dump())],
    )


async def search_similar(client: AsyncQdrantClient, collection_name: str, query_vector: list[float],
                         top_k: int, score_threshold: float | None = None,
                         payload_filter: qmodels.Filter | None = None) -> list[QdrantHit]:
    results = await client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=payload_filter,
        with_payload=True,
    )
    hits: list[QdrantHit] = []
    for point in results:
        payload = point.payload or {}
        try:
            hits.append(QdrantHit(point_id=str(point.id), score=point.score,
                                  payload=ProductPayload.model_validate(payload)))
        except Exception:
            logger.warning("qdrant_hit_payload_invalid", point_id=str(point.id), payload=payload)
    return hits


async def delete_points(client: AsyncQdrantClient, collection_name: str, point_ids: list[str]) -> None:
    if not point_ids:
        return
    await client.delete(collection_name=collection_name,
                        points_selector=qmodels.PointIdsList(points=point_ids))
