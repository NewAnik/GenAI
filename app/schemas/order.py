from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    shipping_address_id: int


class OrderItemResponse(BaseModel):
    id: int
    product_id: int | None = None
    variant_id: int | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None


class InvoiceResponse(BaseModel):
    id: int
    invoice_number: str | None = None
    invoice_url: str | None = None
    gst_amount: Decimal | None = None
    total_amount: Decimal | None = None


class ShipmentResponse(BaseModel):
    id: int
    courier_name: str | None = None
    tracking_number: str | None = None
    shipment_status: str | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None


class OrderSummary(BaseModel):
    id: int
    order_number: str | None = None
    status: str | None = None
    payment_status: str | None = None
    total_amount: Decimal | None = None
    created_at: datetime | None = None


class OrderDetail(OrderSummary):
    shipping_address_id: int | None = None
    items: list[OrderItemResponse] = []
    invoice: InvoiceResponse | None = None
    shipments: list[ShipmentResponse] = []


class CheckoutResponse(BaseModel):
    order_id: int
    order_number: str
    total_amount: Decimal


class CreateShipmentRequest(BaseModel):
    courier_name: str
    tracking_number: str
