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
    # Joined from gift_box_items at request time, e.g. "1 x Cashew and raisin jar, 2 x Clay diya"
    # — there is no separate marketing-copy column (see the migration plan's note on this).
    contents: str
    # Already resolved to a full CDN URL by the handler — never a bare object key.
    image_url: str | None = None
    alt_text: str | None = None
