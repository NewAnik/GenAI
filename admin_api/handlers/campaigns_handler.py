"""Lambda for POST /campaigns/{campaign_id}/recipients/import — replaces
ImportRecipientsDialog.tsx's `supabase.from('campaign_recipients').insert(rows)`. CSV parsing and
per-row validation stay client-side exactly as they are today (splitLine/parse in that file); this
endpoint only does the bulk insert, as one multi-row INSERT rather than N round trips."""
from __future__ import annotations

import msgspec
from db.connection import connection, raw_connection
from db.models.campaigns import Campaign
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.errors import NotFoundError, ValidationError
from handlers.common.http import decode_body, json_response, path_param
from handlers.common.router import dispatch
from psycopg2.extras import execute_values


class RecipientRow(msgspec.Struct, kw_only=True):
    employee_name: str
    employee_email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None


class ImportRequest(msgspec.Struct, kw_only=True):
    rows: list[RecipientRow]


def _import(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)
    campaign_id = path_param(event, "campaign_id")
    if Campaign.get_or_none(Campaign.id == campaign_id) is None:
        raise NotFoundError("no campaign with that id")

    payload = decode_body(event, ImportRequest)
    if not payload.rows:
        raise ValidationError("rows must not be empty")

    values = [
        (campaign_id, r.employee_name, r.employee_email, r.address, r.city, r.state, r.pincode)
        for r in payload.rows
    ]
    conn = raw_connection()
    with conn.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO campaign_recipients "
            "(campaign_id, employee_name, employee_email, address, city, state, pincode) VALUES %s",
            values,
        )
    conn.commit()

    return json_response(201, {"imported": len(values)})


ROUTES = {
    "POST /campaigns/{campaign_id}/recipients/import": _import,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES, context)
