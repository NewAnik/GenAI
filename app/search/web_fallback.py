"""Internet fallback for gift ideas when the internal catalog has nothing good for a niche
ask. Results are tagged `WebIdea` and never conflated with `CatalogHit` — the curation step
and WhatsApp presentation both clearly separate "from our catalog" vs "external idea"."""
from __future__ import annotations

from dataclasses import dataclass

from tavily import AsyncTavilyClient

from app.agent.state import Slots
from app.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class WebIdea:
    title: str
    summary: str
    source_url: str
    source_domain: str

    def to_dict(self) -> dict:
        return {"title": self.title, "summary": self.summary,
                "source_url": self.source_url, "source_domain": self.source_domain}


def _build_query(slots: Slots) -> str:
    pieces = ["corporate gift ideas"]
    if slots.occasion:
        pieces.append(f"for {slots.occasion}")
    if slots.theme_preferences:
        pieces.append(f"theme {', '.join(slots.theme_preferences)}")
    budget = slots.budget_per_recipient or (
        slots.total_budget / slots.recipient_count if slots.total_budget and slots.recipient_count else None
    )
    if budget is not None:
        pieces.append(f"budget around INR {budget:.0f} per person")
    if slots.recipient_count:
        pieces.append(f"bulk order for {slots.recipient_count} recipients")
    pieces.append("India corporate gifting")
    return " ".join(pieces)


def _domain(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.")


async def fetch_web_gift_ideas(slots: Slots, tavily_client: AsyncTavilyClient,
                               max_results: int = 5) -> list[WebIdea]:
    query = _build_query(slots)
    try:
        response = await tavily_client.search(query=query, search_depth="advanced",
                                               max_results=max_results, include_answer=False)
    except Exception:
        logger.exception("tavily_search_failed", query=query)
        return []

    ideas: list[WebIdea] = []
    for result in response.get("results", [])[:max_results]:
        url = result.get("url", "")
        ideas.append(WebIdea(
            title=result.get("title", "Gift idea"),
            summary=(result.get("content") or "")[:280],
            source_url=url,
            source_domain=_domain(url),
        ))
    logger.info("web_fallback_fetched", query=query, idea_count=len(ideas))
    return ideas
