"""Per-turn dependencies injected into every graph node via `config["configurable"]["deps"]`.

This is the standard LangGraph DI seam: it keeps node functions pure of global state and
trivially testable (swap in fakes for the chat model / repos / external clients in tests —
see tests/integration/test_agent_graph_happy_path.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.db.repositories.campaign_repo import CampaignRepository
from app.db.repositories.catalog_repo import CatalogRepository
from app.db.repositories.recommendation_repo import RecommendationLogRepository


@dataclass
class NodeDeps:
    settings: Settings
    catalog_repo: CatalogRepository
    recommendation_repo: RecommendationLogRepository
    campaign_repo: CampaignRepository
    qdrant_client: AsyncQdrantClient
    openai_client: AsyncOpenAI
    tavily_client: Any | None
    chat_model: Any                # BaseChatModel (or a fake, in tests)
    structured: Any                # callable(schema) -> structured-output runnable


def deps_from_config(config: RunnableConfig) -> NodeDeps:
    deps = config.get("configurable", {}).get("deps")
    if deps is None:
        raise RuntimeError("NodeDeps missing from graph config — orchestrator must pass them via "
                           "config={'configurable': {'deps': ...}}")
    return deps
