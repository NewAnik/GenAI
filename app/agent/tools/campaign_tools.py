"""LLM escape-hatch tool: a quick, pure ballpark cost estimate for a bulk gifting order, so the
bot can answer "roughly what would 150 people at ₹500 each cost us?" without guessing arithmetic.

Deliberately read-only / no DB writes — turning a confirmed selection into a real draft
`campaigns`/`quotes` row needs an `organization_id` resolved from the WhatsApp number, which
isn't wired up yet (see the note in `nodes.finalize_selection`). Once that resolution exists,
`deps.campaign_repo.create_draft_campaign(...)` is the place to do it — not here.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

_ESTIMATED_OVERHEAD_RATE = Decimal("0.18")  # rough ballpark for taxes/branding/logistics, clearly framed as such


class QuoteEstimateArgs(BaseModel):
    recipient_count: int = Field(..., description="Number of people receiving a gift", gt=0)
    unit_price: float = Field(..., description="Estimated price per gift, in INR", gt=0)


def build_quote_estimate_tool() -> StructuredTool:
    def _estimate(recipient_count: int, unit_price: float) -> str:
        price = Decimal(str(unit_price))
        subtotal = (price * recipient_count).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        overhead = (subtotal * _ESTIMATED_OVERHEAD_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        rough_total = subtotal + overhead
        return (
            f"Rough ballpark only (not a quote): {recipient_count} x ₹{price} = ₹{subtotal} subtotal, "
            f"plus an estimated ~18% for branding/taxes/logistics (~₹{overhead}), "
            f"landing around ₹{rough_total} total. Final pricing depends on customization and "
            "delivery — our team will confirm an exact quote."
        )

    return StructuredTool.from_function(
        func=_estimate,
        name="estimate_bulk_quote",
        description=(
            "Compute a rough, clearly-labeled ballpark total cost for a bulk gift order given a "
            "recipient count and per-unit price. Always frame the result as an estimate, not a quote."
        ),
        args_schema=QuoteEstimateArgs,
    )
