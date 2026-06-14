"""Integration test: drives the *compiled* LangGraph end to end across three real turns —
greeting -> slot-filling -> search/curate/present -> selection — using the real graph wiring,
real routing functions, and real node logic, with only the external boundaries faked:

  * the chat model's structured-output calls (`deps.structured`) return canned Pydantic objects
  * `search_for_gifts` (the SQL/Qdrant/Tavily hybrid search) is patched to a fixed result

This is the seam the project is designed around (see `app/agent/deps.py`): nodes are pure of
global state and only ever reach the world through `NodeDeps`, so swapping in fakes here
exercises the exact same code paths production traffic does.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.agent.deps import NodeDeps
from app.agent.graph import build_agent_graph
from app.agent.schemas import CurationItem, CurationResult, IntentClassification
from app.agent.slot_schema import ExtractedSlots
from app.agent.state import new_agent_state
from app.config import Settings
from app.db.repositories.catalog_repo import CatalogHit
from app.search.hybrid_search import HybridSearchResult

_WHATSAPP_NUMBER = "919800000000"
_SESSION_ID = 42

_CATALOG_HIT = CatalogHit(
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
    catalog_hits=[_CATALOG_HIT], semantic_hits=[_CATALOG_HIT],
    merged=[_CATALOG_HIT, _GIFT_BOX_HIT], used_web_fallback=False, web_ideas=[],
)

_EXTRACTED_SLOTS = ExtractedSlots(
    occasion="Diwali", recipient_count=50, budget_per_recipient=500.0,
    theme_preferences=["eco-friendly"], branding_needed=False,
)

_CURATION_RESULT = CurationResult(items=[
    CurationItem(rank=1, source_type="catalog_product", ref_id=101,
                 justification="Fits the ~₹500/person Diwali budget and the eco-friendly theme.",
                 fit_tags=["budget_fit", "theme_fit"]),
    CurationItem(rank=2, source_type="catalog_gift_box", ref_id=7,
                 justification="A festive-themed box that suits the Diwali occasion well.",
                 fit_tags=["occasion_fit"]),
])


class _FakeRecommendationRepo:
    def __init__(self):
        self.logged: list[tuple[int, dict]] = []

    async def log(self, session_id, recommendation_json):
        self.logged.append((session_id, recommendation_json))


class _ExplodingChatModel:
    """If a node reaches for the raw chat model in this scripted happy path, that's a scenario
    the test didn't anticipate — fail loudly rather than silently returning nonsense."""

    async def ainvoke(self, *args, **kwargs):
        raise AssertionError("deps.chat_model.ainvoke should not be called in this happy path")


class _FakeStructuredDispatcher:
    """Stands in for `deps.structured`: returns a tiny runnable that ignores the formatted
    prompt and yields a pre-scripted Pydantic response, keyed by requested schema class."""

    def __init__(self, responses: dict[type, object]):
        self._responses = responses

    def __call__(self, schema, **kwargs):
        try:
            response = self._responses[schema]
        except KeyError:
            raise AssertionError(f"No scripted structured-output response for {schema!r}") from None
        return RunnableLambda(lambda _: response)


def _build_deps(recommendation_repo) -> NodeDeps:
    return NodeDeps(
        settings=Settings(_env_file=None),
        catalog_repo=None,
        recommendation_repo=recommendation_repo,
        campaign_repo=None,
        qdrant_client=None,
        openai_client=None,
        tavily_client=None,
        chat_model=_ExplodingChatModel(),
        structured=_FakeStructuredDispatcher({
            ExtractedSlots: _EXTRACTED_SLOTS,
            CurationResult: _CURATION_RESULT,
            IntentClassification: IntentClassification(intent="selection", reason="picked an option"),
        }),
    )


async def test_full_conversation_happy_path_through_selection():
    graph = build_agent_graph()
    repo = _FakeRecommendationRepo()
    deps = _build_deps(repo)
    config = {"configurable": {"deps": deps}, "recursion_limit": 25}

    # --- Turn 1: brand-new conversation -> greeting, end turn -------------------------------
    state = new_agent_state(_WHATSAPP_NUMBER, session_id=_SESSION_ID)
    state["messages"] = [HumanMessage(content="Hi")]

    state = await graph.ainvoke(state, config=config)

    assert state["stage"] == "slot_filling"
    assert state["missing_slots"]
    assert len(state["turn_outbound_messages"]) == 1
    assert state["turn_outbound_messages"][0].kind == "text"
    assert "occasion" in state["turn_outbound_messages"][0].text.lower()

    # --- Turn 2: user gives everything in one go -> search, curate, present -----------------
    state["turn_outbound_messages"] = []
    state["pending_user_action"] = None
    state["messages"] = [*state["messages"], HumanMessage(
        content="We need gifts for our Diwali celebration for about 50 employees, "
                "around ₹500 per person, eco-friendly themes, no branding needed.",
    )]

    with patch("app.agent.nodes.search_catalog.search_for_gifts", return_value=_HYBRID_RESULT):
        state = await graph.ainvoke(state, config=config)

    assert state["slots"].occasion == "Diwali"
    assert state["slots"].recipient_count == 50
    assert state["slots"].budget_per_recipient == Decimal("500.0")
    assert state["stage"] == "presenting"
    assert state["candidates"] == [_CATALOG_HIT.to_dict(), _GIFT_BOX_HIT.to_dict()]
    assert [g.ref_id for g in state["shortlist"]] == [101, 7]
    assert len(repo.logged) == 1
    assert repo.logged[0][0] == _SESSION_ID

    outbound_kinds = [m.kind for m in state["turn_outbound_messages"]]
    assert "interactive_list" in outbound_kinds
    list_message = next(m for m in state["turn_outbound_messages"] if m.kind == "interactive_list")
    row_ids = {row["id"] for section in list_message.sections for row in section["rows"]}
    assert "gift:product:101" in row_ids
    assert "gift:giftbox:7" in row_ids

    # --- Turn 3: user taps the first option -> route straight to finalize_selection ---------
    state["turn_outbound_messages"] = []
    state["pending_user_action"] = "gift:product:101"
    state["messages"] = [*state["messages"], HumanMessage(content="Eco-Friendly Bamboo Hamper")]

    state = await graph.ainvoke(state, config=config)

    assert state["stage"] == "done"
    assert len(repo.logged) == 2
    assert repo.logged[1][1]["event"] == "selection_confirmed"
    assert repo.logged[1][1]["selected"]["ref_id"] == 101
    assert any(m.kind == "text" and "Bamboo Hamper" in (m.text or "")
               for m in state["turn_outbound_messages"])
