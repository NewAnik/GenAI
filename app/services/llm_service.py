"""Centralizes LLM client construction so model choice/temperature/structured-output usage
stays consistent across every agent node (slot extraction, intent classification, refinement
interpretation, curation ranking, free-text replies)."""
from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.config import Settings, get_settings


@lru_cache
def get_chat_model(temperature: float = 0.4) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key or None,
        temperature=temperature,
        timeout=30,
    )


def structured(schema, *, temperature: float = 0.2):
    """Returns a chat model bound to always emit a validated instance of `schema`."""
    return get_chat_model(temperature=temperature).with_structured_output(schema)


@lru_cache
def get_embeddings_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key or None)


def get_settings_for_llm() -> Settings:
    return get_settings()
