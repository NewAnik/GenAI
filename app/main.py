"""FastAPI application factory: wires up the long-lived clients (WhatsApp, Qdrant, OpenAI,
Tavily), constructs the `ConversationOrchestrator`, stores them on `app.state`, and tears
everything down cleanly on shutdown."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from openai import AsyncOpenAI
from tavily import AsyncTavilyClient

from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.payments import router as payments_router
from app.api.webhook import router as webhook_router
from app.config import get_settings
from app.db.session import dispose_engine
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.logging_setup import configure_logging, get_logger
from app.services.conversation_orchestrator import build_orchestrator
from app.vectorstore.qdrant_client import get_qdrant_client
from app.whatsapp.client import WhatsAppClient

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    whatsapp_client = WhatsAppClient(settings)
    qdrant_client = get_qdrant_client(settings)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key or None)
    tavily_client = AsyncTavilyClient(api_key=settings.tavily_api_key) if settings.tavily_api_key else None

    app.state.settings = settings
    app.state.whatsapp_client = whatsapp_client
    app.state.qdrant_client = qdrant_client
    app.state.openai_client = openai_client
    app.state.tavily_client = tavily_client
    app.state.orchestrator = build_orchestrator(
        settings,
        whatsapp_client=whatsapp_client,
        qdrant_client=qdrant_client,
        openai_client=openai_client,
        tavily_client=tavily_client,
    )

    scheduler = start_scheduler(settings)

    logger.info("app_started", env=settings.app_env, tavily_enabled=tavily_client is not None)
    try:
        yield
    finally:
        stop_scheduler(scheduler)
        await whatsapp_client.aclose()
        await qdrant_client.close()
        await openai_client.close()
        await dispose_engine()
        logger.info("app_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="corporate-gifting-ai",
        description="WhatsApp conversational assistant for corporate gifting recommendations.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(auth_router)
    app.include_router(cart_router)
    app.include_router(orders_router)
    app.include_router(payments_router)

    return app


app = create_app()
