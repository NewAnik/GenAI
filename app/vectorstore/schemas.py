"""Payload metadata stored alongside each product vector in Qdrant, plus the search-result type."""
from __future__ import annotations

from pydantic import BaseModel


class ProductPayload(BaseModel):
    product_id: int
    name: str
    category_slug: str | None = None
    brand: str | None = None
    base_price: float | None = None
    is_customizable: bool | None = None
    status: str | None = None


class QdrantHit(BaseModel):
    point_id: str
    score: float
    payload: ProductPayload
