"""Sanity-check DB connectivity and report row counts for the tables this bot depends on.

    python scripts/seed_check.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.db.models import Category, ConversationSession, GiftBox, Product, ProductEmbedding
from app.db.session import dispose_engine, get_session


TABLES = [
    ("products", Product),
    ("categories", Category),
    ("gift_boxes", GiftBox),
    ("product_embeddings", ProductEmbedding),
    ("conversation_sessions", ConversationSession),
]


async def main() -> None:
    async with get_session() as session:
        for label, model in TABLES:
            count = await session.scalar(select(func.count()).select_from(model))
            print(f"{label:<24} {count}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
