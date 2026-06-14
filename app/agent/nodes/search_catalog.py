"""Runs the hybrid catalog search (structured SQL filters ∥ Qdrant semantic search). The
fallback-trigger decision and the Tavily call itself both live inside `search_for_gifts` (it's a
deterministic threshold rule, not an LLM judgment call) — this node just wraps it, stashes the
results onto state, and always proceeds to curation with whatever candidates it found."""
from __future__ import annotations

from app.agent.deps import deps_from_config
from app.agent.state import AgentState
from app.logging_setup import get_logger
from app.search.hybrid_search import search_for_gifts

logger = get_logger(__name__)


async def search_catalog_node(state: AgentState, config) -> dict:
    deps = deps_from_config(config)

    result = await search_for_gifts(
        slots=state["slots"],
        catalog_repo=deps.catalog_repo,
        qdrant_client=deps.qdrant_client,
        openai_client=deps.openai_client,
        tavily_client=deps.tavily_client,
        settings=deps.settings,
    )

    logger.info(
        "catalog_search_completed",
        catalog_hits=len(result.catalog_hits),
        semantic_hits=len(result.semantic_hits),
        merged=len(result.merged),
        used_web_fallback=result.used_web_fallback,
        web_idea_count=len(result.web_ideas),
    )

    return {
        "candidates": [hit.to_dict() for hit in result.merged],
        "web_ideas": [idea.to_dict() for idea in result.web_ideas],
        "used_web_fallback": result.used_web_fallback,
        "stage": "curating",
        "_route": "curate_recommendations",
    }


def route_after_search(state: AgentState) -> str:
    return state.get("_route", "curate_recommendations")  # type: ignore[return-value]
