"""Structured (SQL-filter) half of the hybrid catalog search."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, GiftBox, Product


@dataclass(frozen=True)
class CatalogFilters:
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    category_slugs: list[str] | None = None
    is_customizable: bool | None = None
    min_order_quantity_lte: int | None = None
    include_gift_boxes: bool = True


@dataclass(frozen=True)
class CatalogHit:
    kind: Literal["product", "gift_box"]
    id: int
    name: str
    description: str | None
    price: Decimal
    category_name: str | None
    is_customizable: bool | None
    image_urls: list[str] = field(default_factory=list)
    source: Literal["sql_filter", "semantic", "both"] = "sql_filter"
    similarity_score: float | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": float(self.price) if self.price is not None else None,
            "category_name": self.category_name,
            "is_customizable": self.is_customizable,
            "image_urls": self.image_urls,
            "source": self.source,
            "similarity_score": self.similarity_score,
        }


def _product_to_hit(product: Product, *, source: str = "sql_filter",
                    similarity_score: float | None = None) -> CatalogHit:
    return CatalogHit(
        kind="product",
        id=product.id,
        name=product.name or "",
        description=product.description,
        price=product.base_price or Decimal("0"),
        category_name=product.category.name if product.category else None,
        is_customizable=product.is_customizable,
        image_urls=[img.image_url for img in product.images if img.image_url][:3],
        source=source,  # type: ignore[arg-type]
        similarity_score=similarity_score,
    )


def _gift_box_to_hit(box: GiftBox) -> CatalogHit:
    return CatalogHit(
        kind="gift_box",
        id=box.id,
        name=box.name or "",
        description=box.description,
        price=box.selling_price or Decimal("0"),
        category_name="Gift Box",
        is_customizable=None,
        image_urls=[],
        source="sql_filter",
    )


class CatalogRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def search_by_filters(self, filters: CatalogFilters, limit: int = 50) -> list[CatalogHit]:
        stmt: Select = (
            select(Product)
            .options(selectinload(Product.category), selectinload(Product.images))
            .where(Product.status == "active")
        )
        if filters.min_price is not None:
            stmt = stmt.where(Product.base_price >= filters.min_price)
        if filters.max_price is not None:
            stmt = stmt.where(Product.base_price <= filters.max_price)
        if filters.is_customizable is not None:
            stmt = stmt.where(Product.is_customizable == filters.is_customizable)
        if filters.min_order_quantity_lte is not None:
            stmt = stmt.where(
                or_(Product.min_order_quantity.is_(None),
                    Product.min_order_quantity <= filters.min_order_quantity_lte)
            )
        if filters.category_slugs:
            category_ids = await self._resolve_category_ids(filters.category_slugs)
            if category_ids:
                stmt = stmt.where(Product.category_id.in_(category_ids))

        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        products = result.scalars().unique().all()

        hits = [_product_to_hit(p) for p in products]

        if filters.include_gift_boxes:
            hits.extend(await self.get_gift_boxes_in_budget(filters.min_price, filters.max_price))

        if filters.min_price is not None or filters.max_price is not None:
            mid = _budget_midpoint(filters.min_price, filters.max_price)
            hits.sort(key=lambda h: abs((h.price or Decimal("0")) - mid))

        return hits

    async def get_by_ids(self, product_ids: list[int]) -> list[CatalogHit]:
        if not product_ids:
            return []
        stmt = (
            select(Product)
            .options(selectinload(Product.category), selectinload(Product.images))
            .where(Product.id.in_(product_ids))
        )
        result = await self._session.execute(stmt)
        products = result.scalars().unique().all()
        return [_product_to_hit(p, source="semantic") for p in products]

    async def get_gift_boxes_in_budget(self, min_price: Decimal | None, max_price: Decimal | None,
                                       limit: int = 20) -> list[CatalogHit]:
        stmt = select(GiftBox)
        if min_price is not None:
            stmt = stmt.where(GiftBox.selling_price >= min_price)
        if max_price is not None:
            stmt = stmt.where(GiftBox.selling_price <= max_price)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_gift_box_to_hit(b) for b in result.scalars().all()]

    async def load_category_keyword_index(self) -> dict[str, str]:
        """Best-effort keyword -> category-slug lookup, seeded from the live `categories` table.

        Maps lower-cased category name tokens and slugs to their slug, so theme keywords
        like "eco-friendly" or "tech" can opportunistically resolve to a real category
        filter when there's a lexical match; unmapped themes simply fall through to
        semantic search instead.
        """
        result = await self._session.execute(select(Category.name, Category.slug))
        index: dict[str, str] = {}
        for name, slug in result.all():
            if not slug:
                continue
            index[slug.lower()] = slug
            if name:
                for token in name.lower().replace("-", " ").split():
                    index.setdefault(token, slug)
        return index

    async def _resolve_category_ids(self, slugs: list[str]) -> list[int]:
        """Resolve slugs to category ids, including descendant categories (hierarchical)."""
        result = await self._session.execute(select(Category.id, Category.slug, Category.parent_id))
        rows = result.all()
        slug_set = {s.lower() for s in slugs}
        roots = [cid for cid, slug, _ in rows if slug and slug.lower() in slug_set]
        if not roots:
            return []

        children: dict[int, list[int]] = {}
        for cid, _slug, parent_id in rows:
            if parent_id is not None:
                children.setdefault(parent_id, []).append(cid)

        collected: set[int] = set()
        stack = list(roots)
        while stack:
            cid = stack.pop()
            if cid in collected:
                continue
            collected.add(cid)
            stack.extend(children.get(cid, []))
        return list(collected)


def _budget_midpoint(min_price: Decimal | None, max_price: Decimal | None) -> Decimal:
    if min_price is not None and max_price is not None:
        return (min_price + max_price) / 2
    return min_price or max_price or Decimal("0")
