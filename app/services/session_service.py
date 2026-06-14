"""(De)serializes `AgentState` to/from `conversation_sessions.session_state` JSONB — the
canonical durable store that lets a stateless WhatsApp webhook carry a multi-turn conversation
forward. Loaded at the very start of a turn, persisted at the very end (after outbound sends).

Three load paths, mirroring the plan:
  - no/empty stored state                -> brand-new "new gifting need" (`new_agent_state`)
  - stored state with `stage == "done"`  -> the previous gifting need wrapped up; start another
    fresh one (reset slots/candidates/shortlist) but keep recent message history so the bot
    still feels like it remembers this user
  - stored state, any other stage        -> resume mid-conversation exactly where it left off
"""
from __future__ import annotations

from langchain_core.messages import messages_from_dict, messages_to_dict

from app.agent.state import ALL_SLOT_KEYS, AgentState, RankedGift, Slots, new_agent_state

_RESUME_HISTORY_LIMIT = 6


def load_agent_state(raw_state: dict | None, *, whatsapp_number: str, session_id: int) -> AgentState:
    if not raw_state or not raw_state.get("stage"):
        return new_agent_state(whatsapp_number, session_id)

    if raw_state.get("stage") == "done":
        fresh = new_agent_state(whatsapp_number, session_id)
        fresh["messages"] = messages_from_dict(raw_state.get("messages") or [])[-_RESUME_HISTORY_LIMIT:]
        fresh["stage"] = "slot_filling"
        return fresh

    return _deserialize(raw_state, whatsapp_number=whatsapp_number, session_id=session_id)


def serialize_agent_state(state: AgentState) -> dict:
    return {
        "stage": state["stage"],
        "messages": messages_to_dict(state["messages"]),
        "slots": state["slots"].model_dump(mode="json"),
        "missing_slots": state["missing_slots"],
        "last_question_asked": state["last_question_asked"],
        "candidates": state["candidates"],
        "web_ideas": state["web_ideas"],
        "used_web_fallback": state["used_web_fallback"],
        "shortlist": [gift.model_dump(mode="json") for gift in state["shortlist"]],
        "error": state["error"],
    }


def _deserialize(raw: dict, *, whatsapp_number: str, session_id: int) -> AgentState:
    return AgentState(
        whatsapp_number=whatsapp_number,
        session_id=session_id,
        stage=raw.get("stage", "greeting"),
        messages=messages_from_dict(raw.get("messages") or []),
        slots=Slots.model_validate(raw.get("slots") or {}),
        missing_slots=raw.get("missing_slots") or list(ALL_SLOT_KEYS),
        last_question_asked=raw.get("last_question_asked"),
        candidates=raw.get("candidates") or [],
        web_ideas=raw.get("web_ideas") or [],
        used_web_fallback=bool(raw.get("used_web_fallback", False)),
        shortlist=[RankedGift.model_validate(g) for g in raw.get("shortlist") or []],
        pending_user_action=None,
        refinement_request=None,
        turn_outbound_messages=[],
        error=None,
        _route=None,
    )
