"""Cart endpoints (all require auth): view the active cart and add/update/remove items.
Adding an item snapshots the current variant price and enforces the product's
`min_order_quantity`."""
from __future__ import annotations

from decimal import Decimal

from storefront.db.database import connection
from storefront.db.repositories.cart_repo import CartRepository
from storefront.handlers.common.auth import get_current_user
from storefront.handlers.common.errors import NotFoundError, ValidationError
from storefront.handlers.common.http import decode_body, json_response
from storefront.handlers.common.router import dispatch
from storefront.schemas.cart import (
    AddCartItemRequest,
    CartItemResponse,
    CartResponse,
    UpdateCartItemRequest,
)

_repo = CartRepository()


def _serialize(cart) -> CartResponse:
    items: list[CartItemResponse] = []
    subtotal = Decimal("0")
    for item in _repo.items_for(cart):
        unit_price = item.unit_price_snapshot or Decimal("0")
        line_total = unit_price * (item.quantity or 0)
        subtotal += line_total
        items.append(CartItemResponse(
            id=item.id, variant_id=item.variant_id,
            sku=item.variant.sku if item.variant else None,
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

    variant = _repo.get_variant(payload.variant_id)
    if variant is None:
        raise NotFoundError("variant not found")

    min_qty = variant.product.min_order_quantity if variant.product else None
    if min_qty and payload.quantity < min_qty:
        raise ValidationError(f"minimum order quantity for this product is {min_qty}")

    cart = _repo.get_or_create_active(user.id)
    existing = next((i for i in _repo.items_for(cart) if i.variant_id == payload.variant_id), None)
    if existing is not None:
        existing.quantity = (existing.quantity or 0) + payload.quantity
        existing.save()
    else:
        _repo.add_item(
            cart_id=cart.id, variant_id=payload.variant_id, quantity=payload.quantity,
            unit_price_snapshot=variant.price or Decimal("0"),
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
