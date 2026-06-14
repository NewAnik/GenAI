"""Interprets a refinement request ("cheaper", "more eco-friendly", "for 200 people instead")
via structured output, mutates `Slots` in place, and loops back into `search_catalog` —
preserving message history so context isn't lost (unlike a fresh `new_request`)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from langchain_core.messages import AIMessage

from app.agent.deps import deps_from_config
from app.agent.prompts import REFINEMENT_INTERPRETATION_PROMPT
from app.agent.schemas import RefinementIntent
from app.agent.state import AgentState, OutboundMessage, Slots
from app.logging_setup import get_logger

logger = get_logger(__name__)

_ADJUSTMENT_FACTOR = Decimal("0.8")  # "cheaper" / "pricier" nudge when no concrete number is given

_ACK_BY_ADJUSTMENT = {
    "cheaper": "Got it — let me find some more budget-friendly options.",
    "pricier": "Sure thing — let me look at some more premium picks.",
    "more_recipients": "No problem — adjusting for your group size and searching again.",
    "fewer_recipients": "Got it — adjusting for your group size and searching again.",
    "theme_change": "Got it — let me look for options that match that vibe better.",
    "branding_change": "Understood — factoring that into the search.",
    "more_options": "On it — pulling together a few more options for you.",
    "other": "Got it — let me take another look with that in mind.",
}


async def handle_refinement_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)
    slots = state["slots"]

    refinement_text = state.get("refinement_request") or _latest_human_text(state)
    if not refinement_text:
        # "More options" tap with no specific change requested — just re-search/re-rank as is.
        ack = _ACK_BY_ADJUSTMENT["more_options"]
        return _loop_back_to_search(state, slots, ack)

    chain = REFINEMENT_INTERPRETATION_PROMPT | deps.structured(RefinementIntent)
    interpretation = await chain.ainvoke({
        "current_slots": slots.model_dump(mode="json"),
        "latest_message": refinement_text,
    })
    logger.debug("refinement_interpreted", adjustment_type=interpretation.adjustment_type,
                 updated_value=interpretation.updated_value)

    new_slots = _apply_refinement(slots, interpretation)
    ack = _ACK_BY_ADJUSTMENT.get(interpretation.adjustment_type, _ACK_BY_ADJUSTMENT["other"])

    return _loop_back_to_search(state, new_slots, ack)


def route_after_refinement(state: AgentState) -> str:
    return state.get("_route", "search_catalog")  # type: ignore[return-value]


def _loop_back_to_search(state: AgentState, slots: Slots, ack_text: str) -> dict:
    return {
        "slots": slots,
        "stage": "refining",
        "refinement_request": None,
        "messages": [AIMessage(content=ack_text)],
        "turn_outbound_messages": [*state["turn_outbound_messages"],
                                   OutboundMessage(kind="text", text=ack_text)],
        "_route": "search_catalog",
    }


def _apply_refinement(slots: Slots, interpretation: RefinementIntent) -> Slots:
    updated = slots.model_copy(deep=True)
    value = interpretation.updated_value
    adj = interpretation.adjustment_type

    if adj == "cheaper":
        _nudge_budget(updated, _ADJUSTMENT_FACTOR, value)
    elif adj == "pricier":
        _nudge_budget(updated, Decimal("1") / _ADJUSTMENT_FACTOR, value)
    elif adj in ("more_recipients", "fewer_recipients"):
        count = _parse_int(value)
        if count is not None:
            updated.recipient_count = count
    elif adj == "theme_change" and value:
        themes = {t.lower() for t in updated.theme_preferences}
        if value.lower() not in themes:
            updated.theme_preferences = [*updated.theme_preferences, value]
    elif adj == "branding_change":
        if value is not None:
            lowered = value.lower()
            updated.branding_needed = not any(neg in lowered for neg in ("no", "not", "without"))

    return updated


def _nudge_budget(slots: Slots, factor: Decimal, explicit_value: str | None) -> None:
    explicit = _parse_decimal(explicit_value)
    if explicit is not None:
        if slots.total_budget is not None and not slots.budget_per_recipient:
            slots.total_budget = explicit
        else:
            slots.budget_per_recipient = explicit
            slots.total_budget = None
        return

    if slots.budget_per_recipient is not None:
        slots.budget_per_recipient = (slots.budget_per_recipient * factor).quantize(Decimal("1"))
    elif slots.total_budget is not None:
        slots.total_budget = (slots.total_budget * factor).quantize(Decimal("1"))


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isdigit() or ch == ".")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_int(value: str | None) -> int | None:
    decimal_value = _parse_decimal(value)
    return int(decimal_value) if decimal_value is not None else None


def _latest_human_text(state: AgentState) -> str | None:
    for msg in reversed(state["messages"]):
        if msg.type == "human":
            return msg.content if isinstance(msg.content, str) else None
    return None
