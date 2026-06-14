"""Integration test for `AgentState` <-> `conversation_sessions.session_state` JSONB fidelity —
the mechanism that lets a stateless WhatsApp webhook carry a multi-turn conversation forward.
`serialize_agent_state` produces exactly what gets written to the JSONB column; `load_agent_state`
is what the orchestrator calls with whatever Postgres hands back on the next turn. We round-trip
through `json.dumps`/`json.loads` too, since JSONB storage is what actually happens in production
and it's the thing that would catch a non-JSON-safe value (e.g. a bare `Decimal`) slipping through.
"""
from __future__ import annotations

import json
from decimal import Decimal

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import RankedGift, Slots, new_agent_state
from app.services.session_service import load_agent_state, serialize_agent_state

_WHATSAPP_NUMBER = "919800000000"
_SESSION_ID = 7


def _through_jsonb(state) -> dict:
    """Simulates writing `serialize_agent_state(state)` into a JSONB column and reading it back —
    round-tripping through `json` to guarantee every value is JSON-safe, exactly like Postgres."""
    return json.loads(json.dumps(serialize_agent_state(state)))


def test_brand_new_session_with_no_stored_state_starts_a_fresh_conversation():
    state = load_agent_state(None, whatsapp_number=_WHATSAPP_NUMBER, session_id=_SESSION_ID)

    assert state["stage"] == "greeting"
    assert state["messages"] == []
    assert state["slots"] == Slots()


def test_empty_dict_stored_state_is_treated_as_brand_new():
    state = load_agent_state({}, whatsapp_number=_WHATSAPP_NUMBER, session_id=_SESSION_ID)

    assert state["stage"] == "greeting"


def test_mid_conversation_state_round_trips_with_full_fidelity():
    original = new_agent_state(_WHATSAPP_NUMBER, session_id=_SESSION_ID)
    original["stage"] = "presenting"
    original["messages"] = [
        HumanMessage(content="Need gifts for Diwali, 50 people, ~500 each"),
        AIMessage(content="Here are a few options I'd suggest..."),
    ]
    original["slots"] = Slots(
        occasion="Diwali", recipient_count=50, budget_per_recipient=Decimal("500.00"),
        total_budget=Decimal("25000.00"), theme_preferences=["eco-friendly", "festive"],
        branding_needed=True, delivery_city="Bengaluru",
    )
    original["missing_slots"] = ["delivery_timeline"]
    original["last_question_asked"] = "delivery_timeline"
    original["candidates"] = [{"kind": "product", "id": 101, "name": "Eco Hamper",
                               "price": 480.0, "source": "both", "similarity_score": 0.81}]
    original["web_ideas"] = [{"title": "Personalized desk plants", "summary": "Trending idea",
                              "source_url": "https://example.com/a", "source_domain": "example.com"}]
    original["used_web_fallback"] = True
    original["shortlist"] = [
        RankedGift(rank=1, kind="product", ref_id=101, title="Eco Hamper",
                   price=Decimal("480.00"), image_url="https://example.com/hamper.png",
                   justification="Fits the eco-friendly theme and budget.", fit_tags=["budget_fit"]),
        RankedGift(rank=2, kind="web_idea", ref_id=0, title="Personalized desk plants",
                   source_url="https://example.com/a", justification="A fresh external idea.",
                   fit_tags=["external_idea"]),
    ]
    original["error"] = None

    stored = _through_jsonb(original)
    restored = load_agent_state(stored, whatsapp_number=_WHATSAPP_NUMBER, session_id=_SESSION_ID)

    assert restored["stage"] == "presenting"
    assert restored["whatsapp_number"] == _WHATSAPP_NUMBER
    assert restored["session_id"] == _SESSION_ID
    assert [m.type for m in restored["messages"]] == ["human", "ai"]
    assert [m.content for m in restored["messages"]] == [m.content for m in original["messages"]]

    assert restored["slots"] == original["slots"]
    assert restored["slots"].budget_per_recipient == Decimal("500.00")
    assert restored["slots"].total_budget == Decimal("25000.00")

    assert restored["missing_slots"] == ["delivery_timeline"]
    assert restored["last_question_asked"] == "delivery_timeline"
    assert restored["candidates"] == original["candidates"]
    assert restored["web_ideas"] == original["web_ideas"]
    assert restored["used_web_fallback"] is True

    assert restored["shortlist"] == original["shortlist"]
    assert restored["shortlist"][0].price == Decimal("480.00")

    # Transient, within-turn-only fields must never resurrect from a stored snapshot.
    assert restored["pending_user_action"] is None
    assert restored["refinement_request"] is None
    assert restored["turn_outbound_messages"] == []
    assert restored["_route"] is None


def test_done_stage_starts_a_fresh_gifting_need_but_keeps_recent_history_for_continuity():
    original = new_agent_state(_WHATSAPP_NUMBER, session_id=_SESSION_ID)
    original["stage"] = "done"
    original["messages"] = [HumanMessage(content=f"message {i}") for i in range(10)]
    original["slots"] = Slots(occasion="Diwali", recipient_count=50, budget_per_recipient=Decimal("500"))
    original["shortlist"] = [
        RankedGift(rank=1, kind="product", ref_id=101, title="Eco Hamper", justification="fits"),
    ]

    stored = _through_jsonb(original)
    restored = load_agent_state(stored, whatsapp_number=_WHATSAPP_NUMBER, session_id=_SESSION_ID)

    assert restored["stage"] == "slot_filling"
    assert restored["slots"] == Slots()           # fresh gifting need — slots reset
    assert restored["shortlist"] == []             # previous shortlist cleared
    # Only the most recent messages are kept, for conversational continuity.
    assert len(restored["messages"]) == 6
    assert restored["messages"][-1].content == "message 9"


def test_serialized_state_is_pure_json_safe_with_no_bare_decimals():
    state = new_agent_state(_WHATSAPP_NUMBER, session_id=_SESSION_ID)
    state["slots"] = Slots(budget_per_recipient=Decimal("499.99"), total_budget=Decimal("9999.50"))
    state["shortlist"] = [RankedGift(rank=1, kind="product", ref_id=1, title="Item",
                                     price=Decimal("199.99"), justification="n/a")]

    serialized = serialize_agent_state(state)

    # json.dumps would raise TypeError on a bare Decimal — this is the real assertion.
    raw = json.dumps(serialized)
    assert json.loads(raw)["slots"]["budget_per_recipient"] == "499.99"
    assert json.loads(raw)["shortlist"][0]["price"] == "199.99"
