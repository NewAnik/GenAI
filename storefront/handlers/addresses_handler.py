"""Address endpoints (all require auth): list and create the caller's own shipping addresses.
This is the seam checkout() has always needed and never had — see order_service.checkout()'s
`shipping_address_id` requirement."""
from __future__ import annotations

from db.database import connection
from db.repositories.user_repo import UserRepository
from handlers.common.auth import get_current_user
from handlers.common.http import decode_body, json_response
from handlers.common.router import dispatch
from schemas.address import AddressResponse, CreateAddressRequest

_repo = UserRepository()


def _serialize(address) -> AddressResponse:
    return AddressResponse(
        id=address.id, address_type=address.address_type, recipient_name=address.recipient_name,
        phone=address.phone, line1=address.line1, line2=address.line2, city=address.city,
        state=address.state, pincode=address.pincode,
    )


def _list_addresses(event: dict) -> dict:
    user = get_current_user(event)
    addresses = _repo.list_addresses(user.id)
    return json_response(200, [_serialize(a) for a in addresses])


def _create_address(event: dict) -> dict:
    user = get_current_user(event)
    payload = decode_body(event, CreateAddressRequest)
    address = _repo.create_address(
        user.id, address_type=payload.address_type, recipient_name=payload.recipient_name,
        phone=payload.phone, line1=payload.line1, line2=payload.line2, city=payload.city,
        state=payload.state, pincode=payload.pincode,
    )
    return json_response(201, _serialize(address))


ROUTES = {
    "POST /addresses": _list_addresses,
    "POST /addresses/create": _create_address,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES)
