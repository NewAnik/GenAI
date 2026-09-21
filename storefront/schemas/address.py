from __future__ import annotations

import msgspec


class CreateAddressRequest(msgspec.Struct, kw_only=True):
    address_type: str = "shipping"
    recipient_name: str
    phone: str
    line1: str
    line2: str | None = None
    city: str
    state: str
    pincode: str


class AddressResponse(msgspec.Struct, kw_only=True):
    id: int
    address_type: str | None = None
    recipient_name: str | None = None
    phone: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
