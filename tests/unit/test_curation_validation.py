"""Unit tests for the curation node's defensive post-validation: every `CurationItem` the LLM
returns must reference a real candidate id/kind, or it gets dropped — this is what stops a
hallucinated product id from ever reaching a WhatsApp user as a "real" catalog recommendation.

The chat model is faked with a `RunnableLambda` that ignores the formatted prompt and returns a
fixed `CurationResult`, so these tests exercise only the node's own validation/mapping logic.
"""
from __future__ import annotations

from decimal import Decimal

from langchain_core.runnables import RunnableLambda

from app.agent.deps import NodeDeps
from app.agent.nodes.curate_recommendations import curate_recommendations_node
from app.agent.schemas import CurationItem, CurationResult
from app.agent.state import Slots, new_agent_state

_PRODUCT_CANDIDATE = {
    "kind": "product", "id": 101, "name": "Eco-Friendly Hamper", "description": "Bamboo gift set",
    "price": 450.0, "category_name": "Hampers", "is_customizable": True,
    "image_urls": ["https://example.com/img.png"], "source": "sql_filter", "similarity_score": None,
}
_GIFT_BOX_CANDIDATE = {
    "kind": "gift_box", "id": 7, "name": "Festive Box", "description": "Curated festive box",
    "price": 600.0, "category_name": None, "is_customizable": None,
    "image_urls": [], "source": "sql_filter", "similarity_score": None,
}
_WEB_IDEA = {"title": "Personalized desk plants", "summary": "Trending eco gift idea",
             "source_url": "https://example.com/article", "source_domain": "example.com"}


class _FakeRecommendationRepo:
    def __init__(self):
        self.logged: list[tuple[int, dict]] = []

    async def log(self, session_id, recommendation_json):
        self.logged.append((session_id, recommendation_json))


def _deps_with_fixed_curation(curation_result: CurationResult) -> tuple[NodeDeps, _FakeRecommendationRepo]:
    repo = _FakeRecommendationRepo()
    deps = NodeDeps(
        settings=None, catalog_repo=None, recommendation_repo=repo, campaign_repo=None,
        qdrant_client=None, openai_client=None, tavily_client=None, chat_model=None,
        structured=lambda schema, **kwargs: RunnableLambda(lambda _: curation_result),
    )
    return deps, repo


def _state_with(candidates, web_ideas=None):
    state = new_agent_state("919800000000", session_id=1)
    state["slots"] = Slots(occasion="Diwali", recipient_count=50, budget_per_recipient=Decimal("500"))
    state["candidates"] = candidates
    state["web_ideas"] = web_ideas or []
    return state


async def test_curation_keeps_valid_items_and_drops_hallucinated_ids():
    curation_result = CurationResult(items=[
        CurationItem(rank=1, source_type="catalog_product", ref_id=101,
                     justification="Fits the ~₹500/person budget for 50 recipients.", fit_tags=["budget_fit"]),
        CurationItem(rank=2, source_type="catalog_product", ref_id=999,
                     justification="This id was never in the candidate list.", fit_tags=[]),
        CurationItem(rank=3, source_type="catalog_gift_box", ref_id=7,
                     justification="A festive box matching the Diwali occasion.", fit_tags=["occasion_fit"]),
    ])
    deps, repo = _deps_with_fixed_curation(curation_result)
    state = _state_with([_PRODUCT_CANDIDATE, _GIFT_BOX_CANDIDATE])

    result = await curate_recommendations_node(state, {"configurable": {"deps": deps}})

    shortlist = result["shortlist"]
    assert [g.ref_id for g in shortlist] == [101, 7]
    assert all(g.ref_id != 999 for g in shortlist)
    assert result["_route"] == "present_options"
    assert result["stage"] == "presenting"
    assert len(repo.logged) == 1
    assert repo.logged[0][0] == state["session_id"]


async def test_curation_resolves_web_idea_indices_and_drops_out_of_range():
    curation_result = CurationResult(items=[
        CurationItem(rank=1, source_type="web_idea", ref_id=0,
                     justification="A trending eco-friendly idea worth exploring.", fit_tags=["external_idea"]),
        CurationItem(rank=2, source_type="web_idea", ref_id=5,
                     justification="Out of range — should be dropped.", fit_tags=[]),
    ])
    deps, _ = _deps_with_fixed_curation(curation_result)
    state = _state_with([_PRODUCT_CANDIDATE], web_ideas=[_WEB_IDEA])

    result = await curate_recommendations_node(state, {"configurable": {"deps": deps}})

    shortlist = result["shortlist"]
    assert len(shortlist) == 1
    assert shortlist[0].kind == "web_idea"
    assert shortlist[0].title == _WEB_IDEA["title"]
    assert shortlist[0].source_url == _WEB_IDEA["source_url"]


async def test_curation_with_no_candidates_returns_empty_shortlist_and_asks_to_refine():
    deps, repo = _deps_with_fixed_curation(CurationResult(items=[
        CurationItem(rank=1, source_type="catalog_product", ref_id=1, justification="n/a"),
    ]))
    state = _state_with([], web_ideas=[])

    result = await curate_recommendations_node(state, {"configurable": {"deps": deps}})

    assert result["shortlist"] == []
    assert result["_route"] == "end_turn"
    assert result["stage"] == "slot_filling"
    assert not repo.logged
    assert any(m.kind == "text" for m in result["turn_outbound_messages"])


async def test_curation_drops_all_hallucinated_items_and_falls_back_gracefully():
    curation_result = CurationResult(items=[
        CurationItem(rank=1, source_type="catalog_product", ref_id=12345, justification="invented"),
    ])
    deps, repo = _deps_with_fixed_curation(curation_result)
    state = _state_with([_PRODUCT_CANDIDATE])

    result = await curate_recommendations_node(state, {"configurable": {"deps": deps}})

    assert result["shortlist"] == []
    assert result["_route"] == "end_turn"
    assert not repo.logged
