"""Order endpoints: the atomic checkout, order list/detail, cancellation, invoice and
shipment reads, plus an admin-only shipment-create that fulfills the reservation."""
from __future__ import annotations

from config import get_settings
from db.database import connection
from db.repositories.order_repo import OrderRepository
from handlers.common.auth import get_current_user, require_role
from handlers.common.errors import NotFoundError
from handlers.common.http import decode_body, error_response, json_response
from handlers.common.router import dispatch
from schemas.order import (
    CheckoutRequest,
    CheckoutResponse,
    CreateShipmentRequest,
    InvoiceResponse,
    OrderDetail,
    OrderItemResponse,
    OrderStatusHistoryResponse,
    OrderSummary,
    ShipmentResponse,
)
from services import inventory_service, order_service

_repo = OrderRepository()


def _summary(order) -> OrderSummary:
    return OrderSummary(
        id=order.id, order_number=order.order_number, status=order.status,
        payment_status=order.payment_status, total_amount=order.total_amount,
        created_at=order.created_at,
    )


def _checkout(event: dict) -> dict:
    user = get_current_user(event)
    payload = decode_body(event, CheckoutRequest)
    settings = get_settings()
    try:
        result = order_service.checkout(
            settings, user_id=user.id, org_id=user.organization_id,
            shipping_address_id=payload.shipping_address_id,
        )
    except order_service.EmptyCartError:
        return error_response(400, "empty_cart", "cart is empty")
    except order_service.InvalidAddressError:
        return error_response(400, "invalid_address", "invalid shipping address")
    except inventory_service.InsufficientStockError as exc:
        return error_response(
            409, "insufficient_stock",
            f"insufficient stock for variant {exc.variant_id} "
            f"(requested {exc.requested}, available {exc.available})",
        )
    return json_response(201, CheckoutResponse(
        order_id=result.order_id, order_number=result.order_number, total_amount=result.total_amount,
    ))


def _list_orders(event: dict) -> dict:
    user = get_current_user(event)
    orders = _repo.list_for_user(user.id)
    return json_response(200, [_summary(o) for o in orders])


def _get_order(event: dict) -> dict:
    user = get_current_user(event)
    order_id = int(event["pathParameters"]["order_id"])
    order = _repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise NotFoundError("order not found")

    invoice = _repo.get_invoice(order_id)
    shipments = _repo.get_shipments(order_id)
    items = _repo.get_items(order_id)
    history = _repo.get_status_history(order_id)

    detail = OrderDetail(
        id=order.id, order_number=order.order_number, status=order.status,
        payment_status=order.payment_status, total_amount=order.total_amount,
        created_at=order.created_at, shipping_address_id=order.shipping_address_id,
        items=[
            OrderItemResponse(
                id=i.id, gift_box_slug=i.gift_box.slug if i.gift_box else None,
                name=i.gift_box.name if i.gift_box else None,
                quantity=i.quantity, unit_price=i.unit_price,
            )
            for i in items
        ],
        invoice=(InvoiceResponse(
            id=invoice.id, invoice_number=invoice.invoice_number, invoice_url=invoice.invoice_url,
            gst_amount=invoice.gst_amount, total_amount=invoice.total_amount,
        ) if invoice is not None else None),
        shipments=[
            ShipmentResponse(id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
                              shipment_status=s.shipment_status, shipped_at=s.shipped_at,
                              delivered_at=s.delivered_at)
            for s in shipments
        ],
        status_history=[
            OrderStatusHistoryResponse(id=h.id, status=h.status, note=h.note, created_at=h.created_at)
            for h in history
        ],
    )
    return json_response(200, detail)


def _cancel_order(event: dict) -> dict:
    user = get_current_user(event)
    order_id = int(event["pathParameters"]["order_id"])
    try:
        order_service.cancel_order(order_id=order_id, user_id=user.id)
    except order_service.OrderNotFoundError:
        raise NotFoundError("order not found")
    except order_service.OrderNotCancellableError as exc:
        return error_response(409, "not_cancellable", str(exc))
    order = _repo.get_for_user(order_id, user_id=user.id)
    return json_response(200, _summary(order))


def _get_invoice(event: dict) -> dict:
    user = get_current_user(event)
    order_id = int(event["pathParameters"]["order_id"])
    order = _repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise NotFoundError("order not found")
    invoice = _repo.get_invoice(order_id)
    if invoice is None:
        raise NotFoundError("invoice not found")
    return json_response(200, InvoiceResponse(
        id=invoice.id, invoice_number=invoice.invoice_number, invoice_url=invoice.invoice_url,
        gst_amount=invoice.gst_amount, total_amount=invoice.total_amount,
    ))


def _list_shipments(event: dict) -> dict:
    user = get_current_user(event)
    order_id = int(event["pathParameters"]["order_id"])
    order = _repo.get_for_user(order_id, user_id=user.id)
    if order is None:
        raise NotFoundError("order not found")
    shipments = _repo.get_shipments(order_id)
    return json_response(200, [
        ShipmentResponse(id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
                          shipment_status=s.shipment_status, shipped_at=s.shipped_at,
                          delivered_at=s.delivered_at)
        for s in shipments
    ])


def _create_shipment(event: dict) -> dict:
    require_role(event, "admin")
    order_id = int(event["pathParameters"]["order_id"])
    payload = decode_body(event, CreateShipmentRequest)
    try:
        shipment_id = order_service.record_shipment(
            order_id=order_id, courier_name=payload.courier_name,
            tracking_number=payload.tracking_number,
        )
    except order_service.OrderNotFoundError:
        raise NotFoundError("order not found")
    shipments = _repo.get_shipments(order_id)
    s = next((x for x in shipments if x.id == shipment_id), shipments[-1])
    return json_response(201, ShipmentResponse(
        id=s.id, courier_name=s.courier_name, tracking_number=s.tracking_number,
        shipment_status=s.shipment_status, shipped_at=s.shipped_at, delivered_at=s.delivered_at,
    ))


ROUTES = {
    "POST /checkout": _checkout,
    "POST /orders": _list_orders,
    "POST /orders/{order_id}": _get_order,
    "POST /orders/{order_id}/cancel": _cancel_order,
    "POST /orders/{order_id}/invoice": _get_invoice,
    "POST /orders/{order_id}/shipments": _list_shipments,
    "POST /orders/{order_id}/shipments/create": _create_shipment,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
