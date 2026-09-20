"""Cart endpoints (all require auth): view the active cart and add/update/remove items.
Adding an item snapshots the current gift box's selling price and enforces its `moq`."""
from __future__ import annotations

from decimal import Decimal

from db.database import connection
from db.repositories.cart_repo import CartRepository
from db.repositories.catalog_repo import CatalogRepository
from handlers.common.auth import get_current_user
from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.http import decode_body, json_response
from handlers.common.media import resolve_catalog_image_url
from handlers.common.router import dispatch
from schemas.cart import (
    AddCartItemRequest,
    CartItemResponse,
    CartResponse,
    UpdateCartItemRequest,
)

_repo = CartRepository()
_catalog_repo = CatalogRepository()


def _serialize(cart) -> CartResponse:
    items_raw = _repo.items_for(cart)
    hero_by_box = _catalog_repo.hero_image_by_gift_box(
        [i.gift_box_id for i in items_raw if i.gift_box_id is not None]
    )

    items: list[CartItemResponse] = []
    subtotal = Decimal("0")
    for item in items_raw:
        unit_price = item.unit_price_snapshot or Decimal("0")
        line_total = unit_price * (item.quantity or 0)
        subtotal += line_total
        box = item.gift_box
        hero = hero_by_box.get(item.gift_box_id) if item.gift_box_id else None
        items.append(CartItemResponse(
            id=item.id, gift_box_slug=box.slug if box else None,
            name=box.name if box else None,
            image_url=resolve_catalog_image_url(hero.image_url if hero else None),
            alt_text=hero.alt_text if hero else None,
            quantity=item.quantity, unit_price=unit_price, line_total=line_total,
        ))
    return CartResponse(id=cart.id, status=cart.status, items=items, subtotal=subtotal)


def _get_cart(event: dict) -> dict:
    user = get_current_user(event)
    cart = _repo.get_or_create_active(user.id)
    return json_response(200, _serialize(cart))


def _add_item(event: dict) -> dict:
    user = get_current_user(event)
    payload = decode_body(event, AddCartItemRequest)

    gift_box = _catalog_repo.get_gift_box_by_slug(payload.gift_box_slug)
    if gift_box is None:
        raise NotFoundError("gift box not found")

    if gift_box.moq and payload.quantity < gift_box.moq:
        raise ValidationError(f"minimum order quantity for this box is {gift_box.moq}")

    cart = _repo.get_or_create_active(user.id)
    existing = next((i for i in _repo.items_for(cart) if i.gift_box_id == gift_box.id), None)
    if existing is not None:
        existing.quantity = (existing.quantity or 0) + payload.quantity
        existing.save()
    else:
        _repo.add_item(
            cart_id=cart.id, gift_box_id=gift_box.id, quantity=payload.quantity,
            unit_price_snapshot=gift_box.selling_price or Decimal("0"),
        )

    cart = _repo.get_or_create_active(user.id)
    return json_response(201, _serialize(cart))


def _update_item(event: dict) -> dict:
    user = get_current_user(event)
    item_id = int(event["pathParameters"]["item_id"])
    payload = decode_body(event, UpdateCartItemRequest)

    cart = _repo.get_or_create_active(user.id)
    item = _repo.get_item(item_id, cart_id=cart.id)
    if item is None:
        raise NotFoundError("cart item not found")
    item.quantity = payload.quantity
    item.save()

    cart = _repo.get_or_create_active(user.id)
    return json_response(200, _serialize(cart))


def _remove_item(event: dict) -> dict:
    user = get_current_user(event)
    item_id = int(event["pathParameters"]["item_id"])

    cart = _repo.get_or_create_active(user.id)
    item = _repo.get_item(item_id, cart_id=cart.id)
    if item is None:
        raise NotFoundError("cart item not found")
    _repo.remove_item(item)

    cart = _repo.get_or_create_active(user.id)
    return json_response(200, _serialize(cart))


def _clear_cart(event: dict) -> dict:
    user = get_current_user(event)
    cart = _repo.get_or_create_active(user.id)
    _repo.clear(cart)
    cart = _repo.get_or_create_active(user.id)
    return json_response(200, _serialize(cart))


ROUTES = {
    "POST /cart": _get_cart,
    "POST /cart/items": _add_item,
    "POST /cart/items/{item_id}/update": _update_item,
    "POST /cart/items/{item_id}/remove": _remove_item,
    "POST /cart/clear": _clear_cart,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
