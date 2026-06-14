"""Handles the user picking one of the shown gifts. v1: acknowledges the selection warmly, logs
it for the sales team, and hands off to a human for fulfilment details (quantities, artwork,
delivery address) — that handoff is exactly what corporate gifting buyers expect at this point,
and it sidesteps collecting sensitive payment/address info over chat.

v1.1 stretch (the natural extension point, intentionally not wired up here): turn the selection
into a `campaigns`/`quotes` draft row via `deps.campaign_repo`. Doing that properly needs an
`organization_id`, which means resolving the WhatsApp number to an `org`/`users` record first —
a lookup this node doesn't currently have a repository for. Once that resolution exists, call
`deps.campaign_repo.create_draft_campaign(...)` here with the resolved org and the selected
gift's price/recipient_count from `state["slots"]`.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.deps import deps_from_config
from app.agent.state import AgentState, OutboundMessage, RankedGift
from app.logging_setup import get_logger
from app.whatsapp.inbound import decode_interactive_payload

logger = get_logger(__name__)

async def finalize_selection_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)
    selected = _resolve_selected_gift(state)

    if selected is None:
        message = (
            "I want to make sure I note down the right one — could you tap the option you'd "
            "like from the list above?"
        )
        return {
            "messages": [AIMessage(content=message)],
            "turn_outbound_messages": [*state["turn_outbound_messages"],
                                       OutboundMessage(kind="text", text=message)],
            "_route": "end_turn",
        }

    message = _confirmation_text(selected)

    await deps.recommendation_repo.log(state["session_id"], {
        "event": "selection_confirmed",
        "selected": selected.model_dump(mode="json"),
        "slots": state["slots"].model_dump(mode="json"),
    })
    logger.info("selection_finalized", kind=selected.kind, ref_id=selected.ref_id, title=selected.title)

    return {
        "stage": "done",
        "pending_user_action": None,
        "messages": [AIMessage(content=message)],
        "turn_outbound_messages": [*state["turn_outbound_messages"],
                                   OutboundMessage(kind="text", text=message)],
        "_route": "end_turn",
    }


def route_after_finalize(state: AgentState) -> str:
    return state.get("_route", "end_turn")  # type: ignore[return-value]


def _resolve_selected_gift(state: AgentState) -> RankedGift | None:
    shortlist = state["shortlist"]
    if not shortlist:
        return None

    pending = state.get("pending_user_action")
    if pending:
        namespace, action, ref = decode_interactive_payload(pending)
        if namespace in ("gift", "idea") and ref is not None:
            kind = "web_idea" if namespace == "idea" else ("gift_box" if action == "giftbox" else "product")
            ref_id = _coerce_ref(ref)
            for gift in shortlist:
                if gift.kind == kind and gift.ref_id == ref_id:
                    return gift
        if namespace == "action" and action.startswith("confirm"):
            ref_id = _coerce_ref(ref)
            if ref_id is not None:
                for gift in shortlist:
                    if gift.ref_id == ref_id:
                        return gift

    # Free-text "I'll go with the second one" style selection while presenting: best-effort —
    # fall back to the top-ranked item, since we can't reliably resolve free text to a row here.
    if state["stage"] == "presenting":
        return shortlist[0]
    return None


def _coerce_ref(ref: str) -> int | str | None:
    try:
        return int(ref)
    except (TypeError, ValueError):
        return ref


def _confirmation_text(gift: RankedGift) -> str:
    price_part = f" (around ₹{gift.price:.0f} each)" if gift.price is not None else ""
    return (
        f"Great choice — \"{gift.title}\"{price_part} 🎁 I've noted this down, and one of our "
        "gifting specialists will reach out shortly to confirm quantities, branding, and "
        "delivery. Anything else I can help with?"
    )
