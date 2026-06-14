"""Entry node: figures out what this turn is about and routes to the right next node.

Most routing is deterministic (cheap, fast, predictable) based on `stage` + message type;
the LLM is consulted only for ambiguous free text — keeping cost/latency/non-determinism
under control.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.deps import deps_from_config
from app.agent.prompts import INTENT_ROUTING_PROMPT
from app.agent.schemas import IntentClassification
from app.agent.state import ALL_SLOT_KEYS, AgentState, OutboundMessage, Slots
from app.logging_setup import get_logger
from app.whatsapp.inbound import decode_interactive_payload

logger = get_logger(__name__)

GREETING_TEXT = (
    "Hi! 👋 I'm Gifty — I help put together great corporate gift ideas for your team or clients. "
    "To get started, what's the occasion you're gifting for? (e.g. Diwali, onboarding, "
    "work anniversaries, year-end appreciation)"
)


async def route_intent_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)

    # Brand-new conversation: greet, seed slots, end this turn (one question at a time).
    if state["stage"] == "greeting":
        return {
            "stage": "slot_filling",
            "missing_slots": list(ALL_SLOT_KEYS),
            "messages": [AIMessage(content=GREETING_TEXT)],
            "turn_outbound_messages": [*state["turn_outbound_messages"],
                                       OutboundMessage(kind="text", text=GREETING_TEXT)],
            "last_question_asked": "occasion",
            "_route": "end_turn",
        }

    pending = state.get("pending_user_action")
    if pending:
        namespace, action, ref = decode_interactive_payload(pending)
        if namespace == "gift" or namespace == "idea":
            return {"_route": "finalize_selection"}
        if namespace == "action":
            if action in ("more_options",):
                return {"_route": "present_options"}
            if action in ("refine", "refine_menu"):
                return {"_route": "handle_refinement"}
            if action.startswith("confirm"):
                return {"_route": "finalize_selection"}
        # Unknown interactive payload — fall through to free-text handling of the title text.

    latest_text = _latest_human_text(state)

    if state["stage"] in ("presenting", "refining") and latest_text:
        classification = await _classify_intent(state, deps, latest_text)
        logger.debug("intent_classified", intent=classification.intent, reason=classification.reason)
        if classification.intent == "refinement":
            return {"_route": "handle_refinement", "refinement_request": latest_text}
        if classification.intent == "selection":
            return {"_route": "finalize_selection"}
        if classification.intent == "new_request":
            return {"_route": "collect_requirements", "stage": "slot_filling", "slots": Slots()}
        if classification.intent in ("general_question", "smalltalk"):
            reply = await _smalltalk_reply(state, deps, latest_text)
            return {"messages": [AIMessage(content=reply)],
                    "turn_outbound_messages": [*state["turn_outbound_messages"],
                                               OutboundMessage(kind="text", text=reply)],
                    "_route": "end_turn"}
        # continue_slot_filling falls through

    return {"_route": "collect_requirements"}


def route_after_intent(state: AgentState) -> str:
    return state.get("_route", "collect_requirements")  # type: ignore[return-value]


def _latest_human_text(state: AgentState) -> str | None:
    for msg in reversed(state["messages"]):
        if msg.type == "human":
            return msg.content if isinstance(msg.content, str) else None
    return None


async def _classify_intent(state: AgentState, deps, latest_text: str) -> IntentClassification:
    chain = INTENT_ROUTING_PROMPT | deps.structured(IntentClassification)
    context_summary = (
        f"showed a shortlist of {len(state['shortlist'])} gift option(s)"
        if state["shortlist"] else "were collecting their requirements"
    )
    return await chain.ainvoke({
        "stage": state["stage"],
        "context_summary": context_summary,
        "history": _last_k_messages(state, 6),
        "latest_message": latest_text,
    })


async def _smalltalk_reply(state: AgentState, deps, latest_text: str) -> str:
    response = await deps.chat_model.ainvoke([
        ("system", "You are Gifty, a warm corporate-gifting WhatsApp assistant. Reply briefly "
                   "(1-2 sentences) and steer back to helping them find gifts."),
        ("human", latest_text),
    ])
    return response.content if isinstance(response.content, str) else str(response.content)


def _last_k_messages(state: AgentState, k: int):
    return state["messages"][-k:]
