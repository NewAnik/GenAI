"""Lambda for POST /dashboard/summary — replaces Dashboard.tsx's 5 parallel raw Supabase queries
plus its client-side `useMemo` bucketing. The aggregation (revenue-by-week, orders-by-status) now
happens here, before the response ever reaches the browser, instead of shipping up to 2000 raw
order rows just to bucket them client-side."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from db.connection import connection
from db.models.audit import AuditLog
from db.models.catalog import Product, ProductVariant
from db.models.commerce import Order, Quote
from db.models.inventory import Inventory, Warehouse
from db.models.offers import Offer
from db.models.users import User
from db.repositories.user_repo import STAFF_ROLES
from handlers.common.auth import require_role
from handlers.common.http import json_response
from handlers.common.router import dispatch
from peewee import JOIN

# Orders that represent money actually earned, rather than money hoped for — mirrors
# Dashboard.tsx's REALISED set exactly.
REALISED_STATUSES = {"confirmed", "in_production", "ready_to_ship", "shipped", "delivered"}
OPEN_QUOTE_STATUSES = ("draft", "sent", "under_review")


def _summary(event: dict) -> dict:
    require_role(event, *STAFF_ROLES)

    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=180)
    orders = list(
        Order.select(Order.id, Order.status, Order.total_amount, Order.created_at)
        .where(Order.created_at >= since)
        .order_by(Order.created_at.asc())
        .limit(2000)
    )

    revenue = sum(float(o.total_amount or 0) for o in orders if o.status in REALISED_STATUSES)

    # Bucket the last twelve weeks — weeks with no orders still appear (a zero, not a gap),
    # same reasoning as Dashboard.tsx's original client-side loop.
    today = datetime.now(UTC).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    cursor = today - timedelta(days=(today.weekday() + 1) % 7)
    weeks = []
    for index in range(11, -1, -1):
        start = cursor - timedelta(days=index * 7)
        end = start + timedelta(days=7)
        in_week = [o for o in orders if o.created_at and start <= o.created_at < end]
        weeks.append(
            {
                "label": start.strftime("%b %d"),
                "revenue": sum(
                    float(o.total_amount or 0) for o in in_week if o.status in REALISED_STATUSES
                ),
                "orders": len(in_week),
            }
        )

    by_status: dict[str, int] = {}
    for o in orders:
        if o.status:
            by_status[o.status] = by_status.get(o.status, 0) + 1

    active_offers = Offer.select().where(Offer.status == "active").count()
    open_quotes = Quote.select().where(Quote.status.in_(OPEN_QUOTE_STATUSES)).count()

    low_stock_query = (
        Inventory.select(
            Inventory.id,
            Inventory.quantity,
            Inventory.reserved_quantity,
            Warehouse.name.alias("warehouse_name"),
            ProductVariant.sku.alias("sku"),
            Product.name.alias("product_name"),
        )
        .join(Warehouse)
        .switch(Inventory)
        .join(ProductVariant)
        .join(Product)
        .order_by(Inventory.quantity.asc())
        .limit(60)
    )
    low_stock = []
    for row in low_stock_query.dicts():
        available = (row["quantity"] or 0) - (row["reserved_quantity"] or 0)
        if available <= 15:
            low_stock.append(
                {
                    "id": row["id"],
                    "sku": row["sku"],
                    "product_name": row["product_name"],
                    "warehouse_name": row["warehouse_name"],
                    "available": available,
                }
            )
    low_stock.sort(key=lambda r: r["available"])
    low_stock = low_stock[:8]

    activity = list(
        AuditLog.select(
            AuditLog.id,
            AuditLog.entity_type,
            AuditLog.entity_id,
            AuditLog.action,
            AuditLog.created_at,
            User.first_name.alias("actor_first_name"),
            User.last_name.alias("actor_last_name"),
        )
        .join(User, join_type=JOIN.LEFT_OUTER, on=(AuditLog.performed_by == User.id))
        .order_by(AuditLog.created_at.desc())
        .limit(8)
        .dicts()
    )

    return json_response(
        200,
        {
            "revenue": revenue,
            "orderCount": len(orders),
            "weeks": weeks,
            "byStatus": [{"status": status, "count": count} for status, count in by_status.items()],
            "activeOffers": active_offers,
            "openQuotes": open_quotes,
            "lowStock": low_stock,
            "activity": activity,
        },
    )


ROUTES = {
    "POST /dashboard/summary": _summary,
}


def lambda_handler(event: dict, context=None) -> dict:
    with connection():
        return dispatch(event, ROUTES, context)
