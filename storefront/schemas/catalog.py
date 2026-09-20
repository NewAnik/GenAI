from __future__ import annotations

from decimal import Decimal

import msgspec


class GiftBoxSummary(msgspec.Struct, kw_only=True):
    slug: str
    name: str
    collection: str
    occasions: list[str]
    selling_price: Decimal
    moq: int | None = None
    description: str | None = None
    # Read from gift_boxes.contents_line: admin_api auto-fills it from gift_box_items the first
    # time items are linked (e.g. "1 x Cashew and raisin jar, 2 x Clay diya"), and leaves it alone
    # once an admin has edited it — see admin_api/services/resource_service.py.
    contents: str
    # Already resolved to a full CDN URL by the handler — never a bare object key.
    image_url: str | None = None
    alt_text: str | None = None
