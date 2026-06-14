"""LLM-driven ranking step: turns the merged candidate pool (catalog hits + web ideas) into a
justified 3-5 item shortlist, defends against hallucinated ids/sources via post-validation
against the real candidate set, converts to `RankedGift`, and writes an audit row to
`recommendation_logs`."""
from __future__ import annotations

from decimal import Decimal

from langchain_core.messages import AIMessage

from app.agent.deps import deps_from_config
from app.agent.prompts import CURATION_PROMPT
from app.agent.schemas import CurationResult
from app.agent.state import AgentState, OutboundMessage, RankedGift
from app.logging_setup import get_logger

logger = get_logger(__name__)

_SOURCE_TO_KIND = {
    "catalog_product": "product",
    "catalog_gift_box": "gift_box",
    "web_idea": "web_idea",
}
_KIND_TO_SOURCE_TYPE = {v: k for k, v in _SOURCE_TO_KIND.items()}


async def curate_recommendations_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)
    slots = state["slots"]
    candidates = state["candidates"]
    web_ideas = state["web_ideas"]

    if not candidates and not web_ideas:
        message = (
            "Hmm, I couldn't find a great match yet for what you've described. "
            "Want to tweak the budget or theme a bit so I can look again?"
        )
        return _empty_shortlist_result(state, message)

    valid_keys = {(c["kind"], c["id"]) for c in candidates}
    valid_keys |= {("web_idea", idx) for idx in range(len(web_ideas))}

    chain = CURATION_PROMPT | deps.structured(CurationResult)
    curation = await chain.ainvoke({
        "slots_summary": _slots_summary(slots),
        "catalog_candidates": _format_catalog_candidates(candidates),
        "web_ideas_block": _format_web_ideas_block(web_ideas),
    })

    shortlist: list[RankedGift] = []
    for item in curation.items:
        kind = _SOURCE_TO_KIND.get(item.source_type)
        if kind is None:
            continue
        try:
            ref_id = int(item.ref_id)
        except (TypeError, ValueError):
            logger.warning("curation_dropped_bad_id", source_type=item.source_type, ref_id=item.ref_id)
            continue

        if (kind, ref_id) not in valid_keys:
            logger.warning("curation_dropped_hallucinated_id", kind=kind, ref_id=ref_id)
            continue

        ranked = _to_ranked_gift(kind, ref_id, item, candidates, web_ideas)
        if ranked is not None:
            shortlist.append(ranked)

    if not shortlist:
        message = (
            "I had trouble narrowing this down confidently — could you tell me a bit more about "
            "the theme or vibe you're going for? That'll help me pick better options."
        )
        return _empty_shortlist_result(state, message)

    shortlist.sort(key=lambda g: g.rank)

    recommendation_json = {
        "slots": slots.model_dump(mode="json"),
        "used_web_fallback": state["used_web_fallback"],
        "overall_note": curation.overall_note,
        "items": [g.model_dump(mode="json") for g in shortlist],
    }
    await deps.recommendation_repo.log(state["session_id"], recommendation_json)

    logger.info("curation_completed", shortlist_size=len(shortlist))

    return {"shortlist": shortlist, "stage": "presenting", "_route": "present_options"}


def route_after_curation(state: AgentState) -> str:
    return state.get("_route", "present_options")  # type: ignore[return-value]


def _empty_shortlist_result(state: AgentState, message: str) -> dict:
    return {
        "shortlist": [],
        "stage": "slot_filling",
        "messages": [AIMessage(content=message)],
        "turn_outbound_messages": [*state["turn_outbound_messages"],
                                   OutboundMessage(kind="text", text=message)],
        "_route": "end_turn",
    }


def _to_ranked_gift(kind: str, ref_id: int, item, candidates: list[dict], web_ideas: list[dict]) -> RankedGift | None:
    if kind == "web_idea":
        if ref_id < 0 or ref_id >= len(web_ideas):
            return None
        idea = web_ideas[ref_id]
        return RankedGift(
            rank=item.rank, kind="web_idea", ref_id=ref_id, title=idea.get("title", "Gift idea"),
            price=None, image_url=None, source_url=idea.get("source_url"),
            justification=item.justification, fit_tags=list(item.fit_tags),
        )

    candidate = next((c for c in candidates if c["kind"] == kind and c["id"] == ref_id), None)
    if candidate is None:
        return None
    price = candidate.get("price")
    images = candidate.get("image_urls") or []
    return RankedGift(
        rank=item.rank, kind=kind, ref_id=ref_id, title=candidate.get("name", "Gift"),
        price=Decimal(str(price)) if price is not None else None,
        image_url=images[0] if images else None, source_url=None,
        justification=item.justification, fit_tags=list(item.fit_tags),
    )


def _slots_summary(slots) -> str:
    parts = []
    if slots.occasion:
        parts.append(f"occasion: {slots.occasion}")
    if slots.recipient_count:
        parts.append(f"recipients: {slots.recipient_count}")
    budget = slots.per_recipient_budget()
    if budget is not None:
        parts.append(f"budget per recipient: ~{budget}")
    elif slots.total_budget:
        parts.append(f"total budget: ~{slots.total_budget}")
    if slots.theme_preferences:
        parts.append(f"themes: {', '.join(slots.theme_preferences)}")
    if slots.branding_needed is not None:
        parts.append(f"branding needed: {'yes' if slots.branding_needed else 'no'}")
    if slots.delivery_city:
        parts.append(f"delivery city: {slots.delivery_city}")
    if slots.delivery_timeline:
        parts.append(f"delivery timeline: {slots.delivery_timeline}")
    return "; ".join(parts) if parts else "no specific requirements stated yet"


def _format_catalog_candidates(candidates: list[dict]) -> str:
    if not candidates:
        return "(none — catalog had no good matches for this request)"
    lines = []
    for c in candidates:
        source_type = _KIND_TO_SOURCE_TYPE.get(c["kind"], "catalog_product")
        price = c.get("price")
        price_str = f"₹{price}" if price is not None else "price n/a"
        cust = "customizable/brandable" if c.get("is_customizable") else "not customizable"
        lines.append(
            f"- id={c['id']} kind={source_type} | \"{c['name']}\" | {price_str} | "
            f"category: {c.get('category_name') or 'n/a'} | {cust} | {c.get('description') or ''}".strip()
        )
    return "\n".join(lines)


def _format_web_ideas_block(web_ideas: list[dict]) -> str:
    if not web_ideas:
        return ""
    lines = [
        "Supplementary EXTERNAL ideas (use the index shown as ref_id, source_type=web_idea — "
        "these are NOT in our catalog and can't be ordered directly, only suggested as inspiration):"
    ]
    for idx, idea in enumerate(web_ideas):
        lines.append(f"- id={idx} kind=web_idea | \"{idea.get('title', '')}\" | {idea.get('summary', '')}")
    return "\n".join(lines) + "\n\n"
