"""Lambda for POST /catalog/gift-boxes — the public product grid's data source, replacing
wrapped-and-more's hardcoded src/content/products.ts. The only route in this file (and, along
with the payment webhook, one of only two in the whole storefront API) with `auth: none`: no
`get_current_user` call anywhere here, since browsing the catalogue needs no sign-in."""
from __future__ import annotations

from db.database import connection
from db.repositories.catalog_repo import CatalogRepository
from handlers.common.http import json_response
from handlers.common.media import resolve_catalog_image_url
from handlers.common.router import dispatch
from schemas.catalog import GiftBoxSummary

_repo = CatalogRepository()


def _list_gift_boxes(event: dict) -> dict:
    boxes = _repo.list_gift_boxes()
    box_ids = [box.id for box in boxes]
    hero_by_box = _repo.hero_image_by_gift_box(box_ids)

    summaries = []
    for box in boxes:
        hero = hero_by_box.get(box.id)
        summaries.append(GiftBoxSummary(
            slug=box.slug, name=box.name, collection=box.collection,
            occasions=list(box.occasions or []), selling_price=box.selling_price,
            moq=box.moq, description=box.description,
            contents=box.contents_line or "",
            image_url=resolve_catalog_image_url(hero.image_url if hero else None),
            alt_text=hero.alt_text if hero else None,
        ))
    return json_response(200, summaries)


ROUTES = {
    "POST /catalog/gift-boxes": _list_gift_boxes,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
