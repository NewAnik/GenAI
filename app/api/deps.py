"""FastAPI dependency providers — thin accessors over objects constructed once at startup
and stored on `app.state` (see `app.main.create_app`), plus cached settings."""
from __future__ import annotations

from fastapi import Request

from app.config import Settings, get_settings
from app.services.conversation_orchestrator import ConversationOrchestrator


def get_settings_dep() -> Settings:
    return get_settings()


def get_orchestrator(request: Request) -> ConversationOrchestrator:
    return request.app.state.orchestrator
