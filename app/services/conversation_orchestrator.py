"""The single per-turn entry point: receives one parsed inbound WhatsApp message, runs it
through the compiled LangGraph agent, dispatches whatever outbound messages the graph queued,
and persists the resulting `AgentState` back to `conversation_sessions.session_state` JSONB.

One inbound message -> one `graph.ainvoke` -> zero-or-more outbound sends -> one state save.
Constructed once at app startup (it owns long-lived clients) and stored on `app.state`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient
from tavily import AsyncTavilyClient

from app.agent.deps import NodeDeps
from app.agent.graph import build_agent_graph
from app.agent.state import AgentState, OutboundMessage
from app.config import Settings
from app.db.repositories.campaign_repo import CampaignRepository
from app.db.repositories.catalog_repo import CatalogRepository
from app.db.repositories.recommendation_repo import RecommendationLogRepository
from app.db.repositories.session_repo import SessionRepository
from app.db.session import get_session
from app.logging_setup import bind_turn_context, clear_turn_context, get_logger
from app.services.llm_service import get_chat_model, structured
from app.services.session_service import load_agent_state, serialize_agent_state
from app.whatsapp.client import SendResult, WhatsAppClient
from app.whatsapp.inbound import WhatsAppInboundMessage
from app.whatsapp.outbound_builders import ListRow, ListSection, ReplyButton

logger = get_logger(__name__)


@dataclass
class ConversationOrchestrator:
    settings: Settings
    whatsapp_client: WhatsAppClient
    qdrant_client: AsyncQdrantClient
    openai_client: AsyncOpenAI
    tavily_client: AsyncTavilyClient | None

    def __post_init__(self) -> None:
        self._graph = build_agent_graph()

    async def handle_inbound(self, message: WhatsAppInboundMessage) -> None:
        if not message.is_actionable:
            logger.debug("inbound_message_skipped", message_type=message.message_type,
                         wa_message_id=message.wa_message_id)
            return

        turn_id = uuid.uuid4().hex[:12]
        bind_turn_context(whatsapp_number=message.whatsapp_number, turn_id=turn_id)
        try:
            await self._run_turn(message, turn_id=turn_id)
        finally:
            clear_turn_context()

    async def _run_turn(self, message: WhatsAppInboundMessage, *, turn_id: str) -> None:
        async with get_session() as db_session:
            session_repo = SessionRepository(db_session)
            session_row = await session_repo.get_or_create(message.whatsapp_number)
            raw_state = await session_repo.load_state(message.whatsapp_number)

            state = load_agent_state(raw_state, whatsapp_number=message.whatsapp_number,
                                      session_id=session_row.id)
            bind_turn_context(session_id=session_row.id)

            state = _apply_inbound(state, message)

            deps = NodeDeps(
                settings=self.settings,
                catalog_repo=CatalogRepository(db_session),
                recommendation_repo=RecommendationLogRepository(db_session),
                campaign_repo=CampaignRepository(db_session),
                qdrant_client=self.qdrant_client,
                openai_client=self.openai_client,
                tavily_client=self.tavily_client,
                chat_model=get_chat_model(),
                structured=structured,
            )

            logger.info("turn_started", stage_in=state["stage"], message_type=message.message_type)
            result_state: AgentState = await self._graph.ainvoke(
                state, config={"configurable": {"deps": deps}, "recursion_limit": 25}
            )
            logger.info("turn_graph_completed", stage_out=result_state["stage"],
                        outbound_count=len(result_state["turn_outbound_messages"]))

            await self._dispatch_outbound(result_state)
            await session_repo.save_state(message.whatsapp_number, serialize_agent_state(result_state))

    async def _dispatch_outbound(self, state: AgentState) -> None:
        to = state["whatsapp_number"]
        for outbound in state["turn_outbound_messages"]:
            try:
                result = await self._send_one(to, outbound)
                if not result.ok:
                    logger.warning("outbound_send_not_ok", kind=outbound.kind, raw=result.raw_response)
            except Exception:
                logger.exception("outbound_send_failed", kind=outbound.kind)

    async def _send_one(self, to: str, outbound: OutboundMessage) -> SendResult:
        if outbound.kind == "text":
            return await self.whatsapp_client.send_text(to, outbound.text or "")

        if outbound.kind == "interactive_list":
            sections = [
                ListSection(title=section["title"],
                            rows=[ListRow(**row) for row in section["rows"]])
                for section in (outbound.sections or [])
            ]
            return await self.whatsapp_client.send_interactive_list(
                to, outbound.header, outbound.text or "", outbound.button_text or "Choose", sections,
            )

        if outbound.kind == "interactive_buttons":
            buttons = [ReplyButton(**button) for button in (outbound.buttons or [])]
            return await self.whatsapp_client.send_interactive_buttons(
                to, outbound.text or "", buttons, header=outbound.header,
            )

        if outbound.kind == "image":
            return await self.whatsapp_client.send_image(to, outbound.image_url or "", caption=outbound.caption)

        raise ValueError(f"Unknown outbound message kind: {outbound.kind}")


def _apply_inbound(state: AgentState, message: WhatsAppInboundMessage) -> AgentState:
    """Mutates the freshly-loaded state with this turn's inbound message: clears the previous
    turn's transient fields, records any tapped interactive payload, and appends the human
    message (skipped for pure button/list taps that carry no echoed title text)."""
    state["turn_outbound_messages"] = []
    state["error"] = None

    is_interactive = message.message_type in ("interactive_button_reply", "interactive_list_reply")
    state["pending_user_action"] = message.interactive_id if is_interactive else None

    if message.text:
        state["messages"] = [*state["messages"], HumanMessage(content=message.text)]

    return state


def build_orchestrator(settings: Settings, *, whatsapp_client: WhatsAppClient,
                       qdrant_client: AsyncQdrantClient, openai_client: AsyncOpenAI,
                       tavily_client: AsyncTavilyClient | None) -> ConversationOrchestrator:
    return ConversationOrchestrator(
        settings=settings,
        whatsapp_client=whatsapp_client,
        qdrant_client=qdrant_client,
        openai_client=openai_client,
        tavily_client=tavily_client,
    )
