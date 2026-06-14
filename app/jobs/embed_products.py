"""Incremental, idempotent sync of product embeddings into Qdrant.

Selection is incremental: a product is (re-)embedded if it has no `product_embeddings` row yet,
or its row predates the product's last update (`product_embeddings.created_at < products.updated_at`).
Only `status == 'active'` products are embedded — matching the filter `semantic_search` applies
at query time, so nothing un-searchable ever shows up as a semantic hit.

Each product gets a *deterministic* UUIDv5 Qdrant point id (derived from `product_id`), so
re-running this job is a safe no-op for unchanged products and a clean overwrite for changed
ones — never a duplicate point. `product_embeddings.embedding_id` stores that point id; the
table has no real unique constraint in the source schema (see the model's note), so the
upsert is done at the application level here. Migration `0001_bot_support_indices.py` adds
`uq_product_embeddings_product_id` so this can later become a true DB-level upsert.

Run directly: `python -m app.jobs.embed_products [--dry-run]`
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from openai import AsyncOpenAI
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.db.models import Category, Product, ProductEmbedding
from app.db.session import get_session
from app.logging_setup import configure_logging, get_logger
from app.vectorstore.qdrant_client import ensure_collection, get_qdrant_client, upsert_product_vector
from app.vectorstore.schemas import ProductPayload

logger = get_logger(__name__)

_POINT_ID_NAMESPACE = uuid.NAMESPACE_DNS


async def run_embedding_sync(*, dry_run: bool = False, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    qdrant_client = get_qdrant_client(settings)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key or None)
    stats = {"considered": 0, "embedded": 0}

    try:
        await ensure_collection(qdrant_client, settings.qdrant_collection, settings.openai_embedding_dimensions)

        async with get_session() as session:
            products = await _select_products_needing_embedding(session)
            stats["considered"] = len(products)
            if not products:
                logger.info("embeddings_sync_nothing_to_do")
                return stats

            if dry_run:
                logger.info("embeddings_sync_dry_run", would_embed=len(products),
                            sample=[p.name for p in products[:5]])
                return stats

            for batch in _chunk(products, settings.embeddings_batch_size):
                texts = [_build_embedding_text(p) for p in batch]
                vectors = await _embed_batch(openai_client, settings.openai_embedding_model, texts)

                for product, vector in zip(batch, vectors):
                    point_id = _point_id_for(product.id)
                    payload = ProductPayload(
                        product_id=product.id,
                        name=product.name or "",
                        category_slug=product.category.slug if product.category else None,
                        brand=product.brand,
                        base_price=float(product.base_price) if product.base_price is not None else None,
                        is_customizable=product.is_customizable,
                        status=product.status,
                    )
                    await upsert_product_vector(qdrant_client, settings.qdrant_collection, point_id, vector, payload)
                    await _upsert_embedding_row(session, product_id=product.id, point_id=point_id)
                    stats["embedded"] += 1

                logger.info("embeddings_batch_synced", batch_size=len(batch), total_so_far=stats["embedded"])

        return stats
    finally:
        await qdrant_client.close()
        await openai_client.close()


async def _select_products_needing_embedding(session) -> list[Product]:
    stmt = (
        select(Product)
        .outerjoin(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(
            Product.status == "ACTIVE",
            or_(ProductEmbedding.product_id.is_(None), ProductEmbedding.created_at < Product.updated_at),
        )
        .options(selectinload(Product.category).selectinload(Category.parent))
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def _upsert_embedding_row(session, *, product_id: int, point_id: str) -> None:
    existing = await session.scalar(select(ProductEmbedding).where(ProductEmbedding.product_id == product_id))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if existing is not None:
        existing.embedding_id = point_id
        existing.created_at = now
    else:
        session.add(ProductEmbedding(product_id=product_id, embedding_id=point_id, created_at=now))
    await session.flush()


def _build_embedding_text(product: Product) -> str:
    parts = [product.name or ""]
    category_path = _category_path(product.category)
    if category_path:
        parts.append(category_path)
    if product.brand:
        parts.append(f"by {product.brand}")
    if product.description:
        parts.append(product.description)
    return " | ".join(p for p in parts if p)


def _category_path(category: Category | None) -> str:
    if category is None:
        return ""
    names = [category.name]
    if category.parent is not None:
        names.append(category.parent.name)
    return " > ".join(name for name in reversed(names) if name)


def _point_id_for(product_id: int) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"corporate-gifting-ai.product.{product_id}"))


async def _embed_batch(openai_client: AsyncOpenAI, model: str, texts: list[str]) -> list[list[float]]:
    response = await openai_client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i: i + size]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync product embeddings into Qdrant.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report how many products would be (re-)embedded without calling OpenAI/Qdrant.")
    return parser.parse_args()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = _parse_args()
    stats = asyncio.run(run_embedding_sync(dry_run=args.dry_run, settings=settings))
    logger.info("embeddings_sync_finished", dry_run=args.dry_run, **stats)


if __name__ == "__main__":
    main()
