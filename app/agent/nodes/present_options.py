"""Renders the curated shortlist as WhatsApp messages: an interactive list (sectioned "From our
catalog" vs "More ideas"), a quick-action buttons follow-up, and a couple of product images.

`OutboundMessage.sections`/`buttons` carry plain dicts (JSON-serializable, so the turn's outbound
queue round-trips cleanly through `session_state` if ever needed) shaped exactly like
`whatsapp.outbound_builders.ListSection`/`ListRow`/`ReplyButton` — the dispatch layer in
`services.conversation_orchestrator` rehydrates them into those dataclasses right before calling
`WhatsAppClient`, keeping this node free of transport concerns.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.state import AgentState, OutboundMessage, RankedGift
from app.logging_setup import get_logger

logger = get_logger(__name__)

_MAX_IMAGES = 2

_KIND_TO_PAYLOAD_NAMESPACE = {"product": "gift", "gift_box": "gift", "web_idea": "idea"}
_KIND_TO_PAYLOAD_ACTION = {"product": "product", "gift_box": "giftbox", "web_idea": "web"}


async def present_options_node(state: AgentState, config) -> dict:
    shortlist = state["shortlist"]
    slots = state["slots"]

    intro_text = _build_intro_text(shortlist, slots, used_web_fallback=state["used_web_fallback"])
    list_message = _build_list_message(shortlist)
    button_message = OutboundMessage(
        kind="interactive_buttons",
        text="Want me to keep going?",
        buttons=[
            {"id": "action:more_options", "title": "More options"},
            {"id": "action:refine_menu", "title": "Refine these"},
        ],
    )

    outbound: list[OutboundMessage] = [
        OutboundMessage(kind="text", text=intro_text),
        list_message,
        button_message,
    ]
    outbound.extend(_build_image_messages(shortlist))

    return {
        "stage": "presenting",
        "messages": [AIMessage(content=intro_text)],
        "turn_outbound_messages": [*state["turn_outbound_messages"], *outbound],
        "_route": "end_turn",
    }


def route_after_presentation(state: AgentState) -> str:
    return state.get("_route", "end_turn")  # type: ignore[return-value]


def _build_intro_text(shortlist: list[RankedGift], slots, *, used_web_fallback: bool) -> str:
    occasion = slots.occasion or "this"
    count = len(shortlist)
    base = f"Here are {count} gift ideas I'd suggest for {occasion} 🎁"
    if used_web_fallback and any(g.kind == "web_idea" for g in shortlist):
        base += " — a mix of items from our catalog and a few extra ideas worth exploring."
    else:
        base += " from our catalog, picked for your group and budget."
    base += " Tap one to see more, or use the buttons below to keep refining."
    return base


def _build_list_message(shortlist: list[RankedGift]) -> OutboundMessage:
    catalog_rows = []
    idea_rows = []
    for gift in shortlist:
        namespace = _KIND_TO_PAYLOAD_NAMESPACE[gift.kind]
        action = _KIND_TO_PAYLOAD_ACTION[gift.kind]
        row = {
            "id": f"{namespace}:{action}:{gift.ref_id}",
            "title": gift.title,
            "description": _row_description(gift),
        }
        if gift.kind == "web_idea":
            idea_rows.append(row)
        else:
            catalog_rows.append(row)

    sections = []
    if catalog_rows:
        sections.append({"title": "From our catalog", "rows": catalog_rows})
    if idea_rows:
        sections.append({"title": "More ideas", "rows": idea_rows})

    return OutboundMessage(
        kind="interactive_list",
        header="Your gift shortlist",
        text="Pick an option below to view details or move forward with it.",
        button_text="View options",
        sections=sections,
    )


def _row_description(gift: RankedGift) -> str:
    if gift.price is not None:
        return f"₹{gift.price:.0f} · {gift.justification}"
    return gift.justification


def _build_image_messages(shortlist: list[RankedGift]) -> list[OutboundMessage]:
    images = []
    for gift in shortlist:
        if gift.image_url and len(images) < _MAX_IMAGES:
            images.append(OutboundMessage(
                kind="image",
                image_url=gift.image_url,
                caption=f"{gift.title}" + (f" — ₹{gift.price:.0f}" if gift.price is not None else ""),
            ))
    return images
