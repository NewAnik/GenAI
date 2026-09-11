"""Cart endpoints (all require auth): view the active cart and add/update/remove items.
Adding an item snapshots the current variant price and enforces the product's
`min_order_quantity`."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.models import CartItem, User
from app.db.repositories.cart_repo import CartRepository
from app.schemas.cart import (
    AddCartItemRequest,
    CartItemResponse,
    CartResponse,
    UpdateCartItemRequest,
)

router = APIRouter(prefix="/cart", tags=["cart"])


def _serialize(cart) -> CartResponse:
    items: list[CartItemResponse] = []
    subtotal = Decimal("0")
    for item in cart.items:
        unit_price = item.unit_price_snapshot or Decimal("0")
        line_total = unit_price * (item.quantity or 0)
        subtotal += line_total
        items.append(CartItemResponse(
            id=item.id,
            variant_id=item.variant_id,
            sku=item.variant.sku if item.variant else None,
            quantity=item.quantity,
            unit_price=unit_price,
            line_total=line_total,
        ))
    return CartResponse(id=cart.id, status=cart.status, items=items, subtotal=subtotal)


@router.get("", response_model=CartResponse)
async def get_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> CartResponse:
    cart = await CartRepository(db).get_or_create_active(user.id)
    return _serialize(cart)


@router.post("/items", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def add_item(payload: AddCartItemRequest, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> CartResponse:
    repo = CartRepository(db)
    variant = await repo.get_variant(payload.variant_id)
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="variant not found")

    min_qty = variant.product.min_order_quantity if variant.product else None
    if min_qty and payload.quantity < min_qty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"minimum order quantity for this product is {min_qty}",
        )

    cart = await repo.get_or_create_active(user.id)
    existing = next((i for i in cart.items if i.variant_id == payload.variant_id), None)
    if existing is not None:
        existing.quantity = (existing.quantity or 0) + payload.quantity
    else:
        repo.add_item(CartItem(
            cart_id=cart.id,
            variant_id=payload.variant_id,
            quantity=payload.quantity,
            unit_price_snapshot=variant.price or Decimal("0"),
        ))
    # Reload with items + variants eager-loaded (the SELECT autoflushes the change first).
    cart = await repo.get_or_create_active(user.id)
    return _serialize(cart)


@router.patch("/items/{item_id}", response_model=CartResponse)
async def update_item(item_id: int, payload: UpdateCartItemRequest,
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> CartResponse:
    repo = CartRepository(db)
    cart = await repo.get_or_create_active(user.id)
    item = await repo.get_item(item_id, cart_id=cart.id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cart item not found")
    item.quantity = payload.quantity
    cart = await repo.get_or_create_active(user.id)
    return _serialize(cart)


@router.delete("/items/{item_id}", response_model=CartResponse)
async def remove_item(item_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> CartResponse:
    repo = CartRepository(db)
    cart = await repo.get_or_create_active(user.id)
    item = await repo.get_item(item_id, cart_id=cart.id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cart item not found")
    await repo.remove_item(item)
    cart = await repo.get_or_create_active(user.id)
    return _serialize(cart)


@router.delete("", response_model=CartResponse)
async def clear_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> CartResponse:
    repo = CartRepository(db)
    cart = await repo.get_or_create_active(user.id)
    await repo.clear(cart)
    cart = await repo.get_or_create_active(user.id)
    return _serialize(cart)
