from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import msgspec


class CheckoutRequest(msgspec.Struct, kw_only=True):
    shipping_address_id: int


class OrderItemResponse(msgspec.Struct, kw_only=True):
    id: int
    product_id: int | None = None
    variant_id: int | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None


class InvoiceResponse(msgspec.Struct, kw_only=True):
    id: int
    invoice_number: str | None = None
    invoice_url: str | None = None
    gst_amount: Decimal | None = None
    total_amount: Decimal | None = None


class ShipmentResponse(msgspec.Struct, kw_only=True):
    id: int
    courier_name: str | None = None
    tracking_number: str | None = None
    shipment_status: str | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None


class OrderSummary(msgspec.Struct, kw_only=True):
    id: int
    order_number: str | None = None
    status: str | None = None
    payment_status: str | None = None
    total_amount: Decimal | None = None
    created_at: datetime | None = None


class OrderDetail(OrderSummary, kw_only=True):
    shipping_address_id: int | None = None
    items: list[OrderItemResponse] = msgspec.field(default_factory=list)
    invoice: InvoiceResponse | None = None
    shipments: list[ShipmentResponse] = msgspec.field(default_factory=list)


class CheckoutResponse(msgspec.Struct, kw_only=True):
    order_id: int
    order_number: str
    total_amount: Decimal


class CreateShipmentRequest(msgspec.Struct, kw_only=True):
    courier_name: str
    tracking_number: str
