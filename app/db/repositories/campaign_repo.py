"""v1.1 stretch: draft campaign/quote creation, the clean extension point for
`finalize_selection` to hand a confirmed gift selection off to human sales follow-up."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, Quote, QuoteItem


class CampaignRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_draft_campaign(self, *, organization_id: int, campaign_name: str,
                                     budget: Decimal, employee_count: int, event_type: str) -> Campaign:
        campaign = Campaign(
            organization_id=organization_id,
            campaign_name=campaign_name,
            budget=budget,
            employee_count=employee_count,
            event_type=event_type,
            status="draft",
        )
        self._session.add(campaign)
        await self._session.flush()
        return campaign

    async def create_draft_quote(self, *, organization_id: int, created_by: int | None,
                                 items: list[tuple[int, int, Decimal]]) -> Quote:
        """`items` is a list of (product_id, quantity, unit_price)."""
        total = sum((qty * price for _pid, qty, price in items), Decimal("0"))
        quote = Quote(
            organization_id=organization_id,
            status="draft",
            total_amount=total,
            created_by=created_by,
        )
        self._session.add(quote)
        await self._session.flush()

        for product_id, quantity, unit_price in items:
            self._session.add(
                QuoteItem(quote_id=quote.id, product_id=product_id, quantity=quantity, unit_price=unit_price)
            )
        await self._session.flush()
        return quote
