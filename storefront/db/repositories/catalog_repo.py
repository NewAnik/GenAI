"""Public product-catalogue reads for the storefront's marketing/collection pages — the read
path behind POST /catalog/gift-boxes (see handlers/catalog_handler.py). No auth, no per-user
scoping, unlike every other repository in this package."""
from __future__ import annotations

from db.models import GiftBox, GiftBoxImage


class CatalogRepository:
    def list_gift_boxes(self) -> list[GiftBox]:
        """Only boxes with both a slug and a collection are "catalog-ready" — the two fields the
        admin's create form requires for new entries. There's no separate publish/status flag;
        this is the signal until one is actually needed."""
        return list(
            GiftBox.select()
            .where(GiftBox.slug.is_null(False), GiftBox.collection.is_null(False))
            .order_by(GiftBox.name)
        )

    def hero_image_by_gift_box(self, gift_box_ids: list[int]) -> dict[int, GiftBoxImage]:
        """The lowest `display_order` per box — same "hero" convention as the admin's image
        gallery. Grouped in Python rather than a `DISTINCT ON`/window-function query, since the
        number of boxes on a marketing site is small (mirrors
        admin_api/handlers/dashboard_handler.py's low-stock grouping style)."""
        if not gift_box_ids:
            return {}
        best: dict[int, GiftBoxImage] = {}
        query = GiftBoxImage.select().where(GiftBoxImage.gift_box.in_(gift_box_ids))
        for image in query:
            current = best.get(image.gift_box)
            if current is None or (image.display_order or 0) < (current.display_order or 0):
                best[image.gift_box.id] = image
        return best
