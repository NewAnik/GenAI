"""Slot-filling node: extract -> merge -> evaluate completeness -> ask the next natural
question (one or two trivial slots at a time) or move on to search."""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.deps import deps_from_config
from app.agent.prompts import NEXT_QUESTION_PROMPT, SLOT_EXTRACTION_PROMPT
from app.agent.slot_schema import (
    SLOT_DESCRIPTIONS,
    ExtractedSlots,
    compute_missing_slots,
    is_sufficient_for_search,
    merge_slots,
    next_question_slots,
)
from app.agent.state import AgentState, OutboundMessage
from app.logging_setup import get_logger

logger = get_logger(__name__)


async def collect_requirements_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)
    latest_text = _latest_human_text(state)

    slots = state["slots"]
    if latest_text:
        extraction_chain = SLOT_EXTRACTION_PROMPT | deps.structured(ExtractedSlots)
        extracted = await extraction_chain.ainvoke({
            "current_slots": slots.model_dump(mode="json"),
            "history": state["messages"][-6:-1],
            "latest_message": latest_text,
        })
        slots = merge_slots(slots, extracted)
        logger.debug("slots_merged", slots=slots.model_dump(mode="json"))

    missing = compute_missing_slots(slots)

    if is_sufficient_for_search(slots):
        return {"slots": slots, "missing_slots": missing, "stage": "searching", "_route": "search_catalog"}

    question_keys, bundle_template = next_question_slots(missing)
    question_text = await _phrase_question(state, deps, question_keys, bundle_template)

    return {
        "slots": slots,
        "missing_slots": missing,
        "last_question_asked": question_keys[0] if question_keys else None,
        "messages": [AIMessage(content=question_text)],
        "turn_outbound_messages": [*state["turn_outbound_messages"],
                                   OutboundMessage(kind="text", text=question_text)],
        "stage": "slot_filling",
        "_route": "end_turn",
    }


def route_after_collection(state: AgentState) -> str:
    return state.get("_route", "end_turn")  # type: ignore[return-value]


async def _phrase_question(state: AgentState, deps, question_keys: list[str], bundle_template: str | None) -> str:
    if bundle_template:
        topic_description = bundle_template
        bundle_hint = "Use this phrasing as inspiration but make it sound natural and warm: "
    else:
        key = question_keys[0] if question_keys else "occasion"
        topic_description = SLOT_DESCRIPTIONS.get(key, key)
        bundle_hint = ""

    chain = NEXT_QUESTION_PROMPT | deps.chat_model
    response = await chain.ainvoke({
        "topic_description": topic_description,
        "bundle_hint": bundle_hint,
        "history": state["messages"][-4:],
    })
    content = response.content
    return content if isinstance(content, str) else str(content)


def _latest_human_text(state: AgentState) -> str | None:
    for msg in reversed(state["messages"]):
        if msg.type == "human":
            return msg.content if isinstance(msg.content, str) else None
    return None
