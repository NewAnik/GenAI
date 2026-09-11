"""Order endpoints: the atomic checkout, order list/detail, cancellation, invoice and
shipment reads, plus an admin-only shipment-create that fulfills the reservation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings_dep, require_role
from app.config import Settings
from app.db.models import Order, User
from app.db.repositories.order_repo import OrderRepository
from app.schemas.order import (
    CheckoutRequest,
    CheckoutResponse,
    CreateShipmentRequest,
    InvoiceResponse,
    OrderDetail,
    OrderItemResponse,
    OrderSummary,
    ShipmentResponse,
)
from app.services import inventory_service, order_service

router = APIRouter(tags=["orders"])


def _summary(order: Order) -> OrderSummary:
    return OrderSummary(
        id=order.id, order_number=order.order_number, status=order.status,
        payment_status=order.payment_status, total_amount=order.total_amount,
        created_at=order.created_at,
    )


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
async def checkout(payload: CheckoutRequest, user: User = Depends(get_current_user),
                   settings: Settings = Depends(get_settings_dep)) -> CheckoutResponse:
    try:
        result = await order_service.checkout(
            settings, user_id=user.id, org_id=user.organization_id,
            shipping_address_id=payload.shipping_address_id,
        )
    except order_service.EmptyCartError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cart is empty")
    except order_service.InvalidAddressError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid shipping address")
    except inventory_service.InsufficientStockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"insufficient stock for variant {exc.variant_id} (requested {exc.requested}, available {exc.available})",
        )
    return CheckoutResponse(order_id=result.order_id, order_number=result.order_number,
                            total_amount=result.total_amount)


@router.get("/orders", response_model=list[OrderSummary])
async def list_orders(user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> list[OrderSummary]:
    orders = await OrderRepository(db).list_for_user(user.id)
    return [_summary(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(order_id: int, user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> OrderDetail:
    repo = OrderRepository(db)
    order = await repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")

    invoice = await repo.get_invoice(order_id)
    shipments = await repo.get_shipments(order_id)
    detail = OrderDetail(**_summary(order).model_dump(), shipping_address_id=order.shipping_address_id)
    detail.items = [
        OrderItemResponse(id=i.id, product_id=i.product_id, variant_id=i.variant_id,
                          quantity=i.quantity, unit_price=i.unit_price)
        for i in order.items
    ]
    if invoice is not None:
        detail.invoice = InvoiceResponse(
            id=invoice.id, invoice_number=invoice.invoice_number, invoice_url=invoice.invoice_url,
            gst_amount=invoice.gst_amount, total_amount=invoice.total_amount,
        )
    detail.shipments = [
        ShipmentResponse(id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
                         shipment_status=s.shipment_status, shipped_at=s.shipped_at,
                         delivered_at=s.delivered_at)
        for s in shipments
    ]
    return detail


@router.post("/orders/{order_id}/cancel", response_model=OrderSummary)
async def cancel_order(order_id: int, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> OrderSummary:
    try:
        await order_service.cancel_order(order_id=order_id, user_id=user.id)
    except order_service.OrderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    except order_service.OrderNotCancellableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    order = await OrderRepository(db).get_for_user(order_id, user_id=user.id)
    return _summary(order)


@router.get("/orders/{order_id}/invoice", response_model=InvoiceResponse)
async def get_invoice(order_id: int, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)) -> InvoiceResponse:
    repo = OrderRepository(db)
    order = await repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    invoice = await repo.get_invoice(order_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return InvoiceResponse(
        id=invoice.id, invoice_number=invoice.invoice_number, invoice_url=invoice.invoice_url,
        gst_amount=invoice.gst_amount, total_amount=invoice.total_amount,
    )


@router.get("/orders/{order_id}/shipments", response_model=list[ShipmentResponse])
async def list_shipments(order_id: int, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)) -> list[ShipmentResponse]:
    repo = OrderRepository(db)
    order = await repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    shipments = await repo.get_shipments(order_id)
    return [
        ShipmentResponse(id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
                         shipment_status=s.shipment_status, shipped_at=s.shipped_at,
                         delivered_at=s.delivered_at)
        for s in shipments
    ]


@router.post("/orders/{order_id}/shipments", response_model=ShipmentResponse,
             status_code=status.HTTP_201_CREATED)
async def create_shipment(order_id: int, payload: CreateShipmentRequest,
                          _admin: User = Depends(require_role("admin")),
                          db: AsyncSession = Depends(get_db)) -> ShipmentResponse:
    try:
        shipment_id = await order_service.record_shipment(
            order_id=order_id, courier_name=payload.courier_name,
            tracking_number=payload.tracking_number,
        )
    except order_service.OrderNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    shipments = await OrderRepository(db).get_shipments(order_id)
    s = next((x for x in shipments if x.id == shipment_id), shipments[-1])
    return ShipmentResponse(id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
                            shipment_status=s.shipment_status, shipped_at=s.shipped_at,
                            delivered_at=s.delivered_at)
