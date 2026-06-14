"""Drives a YAML-scripted conversation through the real compiled LangGraph, turn by turn,
asserting the stage/outbound expectations declared alongside each turn.

This is the "fast, reproducible end-to-end conversation smoke test" layer: real graph wiring,
real routing and node logic, real WhatsApp message shapes — with only the external boundaries
(chat-model structured output and the SQL/Qdrant/Tavily hybrid search) replaced by deterministic
fakes, so a fixture always produces the same result with no OpenAI/Meta/DB calls.

The catalog "world" (candidates + curated shortlist) is one fixed canned scenario shared by every
fixture — these are conversation-shape smoke tests, not an LLM-response permutation matrix (that
finer-grained coverage already lives in tests/unit and tests/integration). The one LLM output that
legitimately varies with what the user said — slot extraction, intent classification, refinement
interpretation — is scripted per turn via the fixture's `extracted_slots` / `intent_classification`
/ `refinement_intent` blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.agent.deps import NodeDeps
from app.agent.graph import build_agent_graph
from app.agent.schemas import CurationItem, CurationResult, IntentClassification, RefinementIntent
from app.agent.slot_schema import ExtractedSlots
from app.agent.state import AgentState, OutboundMessage, new_agent_state
from app.config import Settings
from app.db.repositories.catalog_repo import CatalogHit
from app.search.hybrid_search import HybridSearchResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_WHATSAPP_NUMBER = "919800000000"
_SESSION_ID = 99

# --- The one canned "world": catalog candidates + the shortlist the curator distills them to ---

_PRODUCT_HIT = CatalogHit(
    kind="product", id=101, name="Eco-Friendly Bamboo Hamper", description="A curated bamboo gift set",
    price=Decimal("480.00"), category_name="Hampers", is_customizable=True,
    image_urls=["https://example.com/hamper.png"], source="both", similarity_score=0.81,
)
_GIFT_BOX_HIT = CatalogHit(
    kind="gift_box", id=7, name="Festive Discovery Box", description="A festive themed box",
    price=Decimal("520.00"), category_name=None, is_customizable=None,
    image_urls=[], source="sql_filter", similarity_score=None,
)
_HYBRID_RESULT = HybridSearchResult(
    catalog_hits=[_PRODUCT_HIT], semantic_hits=[_PRODUCT_HIT],
    merged=[_PRODUCT_HIT, _GIFT_BOX_HIT], used_web_fallback=False, web_ideas=[],
)
_CURATION_RESULT = CurationResult(items=[
    CurationItem(rank=1, source_type="catalog_product", ref_id=101,
                 justification="Fits the budget and the eco-friendly theme nicely.",
                 fit_tags=["budget_fit", "theme_fit"]),
    CurationItem(rank=2, source_type="catalog_gift_box", ref_id=7,
                 justification="A festive-themed box that suits the occasion.",
                 fit_tags=["occasion_fit"]),
])

_SCHEMA_BY_FIXTURE_KEY = {
    "extracted_slots": ExtractedSlots,
    "intent_classification": IntentClassification,
    "refinement_intent": RefinementIntent,
}
_DEFAULT_RESPONSES: dict[type, Any] = {CurationResult: _CURATION_RESULT}


class _FakeRecommendationRepo:
    def __init__(self) -> None:
        self.logged: list[tuple[int, dict]] = []

    async def log(self, session_id: int, recommendation_json: dict) -> None:
        self.logged.append((session_id, recommendation_json))


class _ExplodingChatModel:
    """Raw `chat_model.ainvoke` is only reached for free-text "next question" phrasing and
    smalltalk replies — scenarios this scripted-conversation layer deliberately avoids by giving
    every fixture's first substantive message enough to satisfy slot-filling in one go. Reaching
    here means a fixture drifted into a path this runner doesn't script for."""

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "deps.chat_model.ainvoke was reached — this scripted runner only canned "
            "structured-output responses; design the fixture to avoid free-text LLM phrasing."
        )


class _ScriptedStructuredDispatcher:
    """Stands in for `deps.structured`. Each turn may queue a one-shot canned response per
    schema (from the fixture's `extracted_slots` / `intent_classification` / `refinement_intent`
    blocks); anything not queued for this turn falls back to `_DEFAULT_RESPONSES`, and anything
    with neither raises — so a fixture that reaches an unscripted LLM call fails loudly and
    points at exactly what's missing, rather than silently producing nonsense.
    """

    def __init__(self) -> None:
        self._queued: dict[type, Any] = {}

    def queue(self, schema: type, response: Any) -> None:
        self._queued[schema] = response

    def __call__(self, schema: type, **kwargs: Any) -> RunnableLambda:
        if schema in self._queued:
            response = self._queued.pop(schema)
        elif schema in _DEFAULT_RESPONSES:
            response = _DEFAULT_RESPONSES[schema]
        else:
            raise AssertionError(
                f"No scripted or default structured-output response for {schema.__name__} — "
                f"add an `{_fixture_key_for(schema)}:` block to this turn in the fixture."
            )
        return RunnableLambda(lambda _: response)


def _fixture_key_for(schema: type) -> str:
    for key, mapped in _SCHEMA_BY_FIXTURE_KEY.items():
        if mapped is schema:
            return key
    return schema.__name__.lower()


@dataclass
class ConversationRun:
    fixture_name: str
    final_state: AgentState
    recommendation_log: list[tuple[int, dict]] = field(default_factory=list)


def load_fixture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def iter_fixture_paths() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("*.yaml"))


async def run_fixture(fixture: dict[str, Any]) -> ConversationRun:
    name = fixture["name"]
    graph = build_agent_graph()
    repo = _FakeRecommendationRepo()
    dispatcher = _ScriptedStructuredDispatcher()
    deps = NodeDeps(
        settings=Settings(_env_file=None), catalog_repo=None, recommendation_repo=repo,
        campaign_repo=None, qdrant_client=None, openai_client=None, tavily_client=None,
        chat_model=_ExplodingChatModel(), structured=dispatcher,
    )
    config = {"configurable": {"deps": deps}, "recursion_limit": 25}

    state = new_agent_state(_WHATSAPP_NUMBER, session_id=_SESSION_ID)

    for turn_index, turn in enumerate(fixture["turns"], start=1):
        _apply_turn_input(state, turn)
        for fixture_key, schema in _SCHEMA_BY_FIXTURE_KEY.items():
            if fixture_key in turn:
                dispatcher.queue(schema, schema(**turn[fixture_key]))

        with patch("app.agent.nodes.search_catalog.search_for_gifts", return_value=_HYBRID_RESULT):
            state = await graph.ainvoke(state, config=config)

        _assert_turn_expectations(name, turn_index, state, turn.get("expect") or {})

    return ConversationRun(fixture_name=name, final_state=state, recommendation_log=repo.logged)


def _apply_turn_input(state: AgentState, turn: dict[str, Any]) -> None:
    """Mirrors what `conversation_orchestrator._apply_inbound` does to freshly-loaded state at
    the start of a real turn: clear last turn's outbound queue, record any tapped payload, and
    append the inbound text (the user's typed message, or the echoed title of a tapped row)."""
    state["turn_outbound_messages"] = []
    state["pending_user_action"] = turn.get("tap")
    text = turn.get("say")
    if text:
        state["messages"] = [*state["messages"], HumanMessage(content=text)]


def _assert_turn_expectations(fixture_name: str, turn_index: int, state: AgentState,
                              expectation: dict[str, Any]) -> None:
    where = f"{fixture_name} (turn {turn_index})"

    if "stage" in expectation:
        assert state["stage"] == expectation["stage"], (
            f"{where}: expected stage {expectation['stage']!r}, got {state['stage']!r}")

    # In-order subsequence match, not strict positional equality: nodes are free to prepend
    # extra messages (e.g. a refinement "got it, searching again" ack) without breaking a
    # fixture that only cares that certain messages appear, in a certain relative order.
    actual_outbound = state["turn_outbound_messages"]
    cursor = 0
    for expected_msg in expectation.get("outbound") or []:
        match_at = next((i for i in range(cursor, len(actual_outbound))
                         if _outbound_message_matches(actual_outbound[i], expected_msg)), None)
        assert match_at is not None, (
            f"{where}: no outbound message matching {expected_msg!r} at/after position {cursor} "
            f"in {[(m.kind, m.text) for m in actual_outbound]}")
        cursor = match_at + 1

    for expected_row_id in expectation.get("list_row_ids") or []:
        list_message = next((m for m in actual_outbound if m.kind == "interactive_list"), None)
        assert list_message is not None, f"{where}: expected an interactive_list message"
        row_ids = {row["id"] for section in (list_message.sections or []) for row in section["rows"]}
        assert expected_row_id in row_ids, f"{where}: expected list row id {expected_row_id!r} in {row_ids}"


def _outbound_message_matches(actual: OutboundMessage, expected: dict[str, Any]) -> bool:
    if "kind" in expected and actual.kind != expected["kind"]:
        return False
    if "contains" in expected:
        haystack = " ".join(filter(None, [actual.text, actual.header, actual.caption]))
        if expected["contains"].lower() not in haystack.lower():
            return False
    return True
