"""LLM escape-hatch tool: ad-hoc web search for general gifting questions the deterministic
pipeline doesn't cover (e.g. "what's trending for Diwali corporate gifts this year?"). Distinct
from `search.web_fallback.fetch_web_gift_ideas` — that one feeds the structured curation step
with `WebIdea` objects; this one returns a short prose summary directly to an LLM tool-call."""
from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from tavily import AsyncTavilyClient

from app.logging_setup import get_logger

logger = get_logger(__name__)

_MAX_RESULTS = 4


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="A focused web search query, e.g. 'trending Diwali corporate gifts India 2026'")


def build_web_search_tool(tavily_client: AsyncTavilyClient | None) -> StructuredTool:
    async def _search(query: str) -> str:
        if tavily_client is None:
            return "Web search isn't available right now."
        try:
            response = await tavily_client.search(query=query, search_depth="basic",
                                                    max_results=_MAX_RESULTS, include_answer=False)
        except Exception:
            logger.exception("tavily_tool_search_failed", query=query)
            return "Web search failed — answer from general knowledge only, and say you're not certain."

        results = response.get("results", [])[:_MAX_RESULTS]
        if not results:
            return "No relevant web results found."
        lines = [f"- {r.get('title', '')}: {(r.get('content') or '')[:200]}" for r in results]
        return "Web search results:\n" + "\n".join(lines)

    return StructuredTool.from_function(
        coroutine=_search,
        name="search_the_web",
        description="Search the public web for general gifting trends/info not in our catalog.",
        args_schema=WebSearchArgs,
    )
