"""LangGraph agent state: the shape that flows through every node in a single turn, and is
(de)serialized to/from `conversation_sessions.session_state` JSONB between turns."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

Stage = Literal["greeting", "slot_filling", "searching", "curating",
                "presenting", "refining", "finalizing", "done"]

OutboundKind = Literal["text", "interactive_list", "interactive_buttons", "image"]


class Slots(BaseModel):
    """The gifting requirement set the bot conversationally fills in over a few turns."""

    occasion: str | None = None
    recipient_count: int | None = None
    budget_per_recipient: Decimal | None = None
    total_budget: Decimal | None = None
    theme_preferences: list[str] = Field(default_factory=list)
    branding_needed: bool | None = None
    delivery_city: str | None = None
    delivery_timeline: str | None = None
    organization_hint: str | None = None

    def has_budget_signal(self) -> bool:
        return self.budget_per_recipient is not None or self.total_budget is not None

    def per_recipient_budget(self) -> Decimal | None:
        if self.budget_per_recipient is not None:
            return self.budget_per_recipient
        if self.total_budget is not None and self.recipient_count:
            return self.total_budget / self.recipient_count
        return None


class RankedGift(BaseModel):
    rank: int
    kind: Literal["product", "gift_box", "web_idea"]
    ref_id: int | str | None
    title: str
    price: Decimal | None = None
    image_url: str | None = None
    source_url: str | None = None
    justification: str
    fit_tags: list[str] = Field(default_factory=list)


class OutboundMessage(BaseModel):
    kind: OutboundKind
    text: str | None = None
    header: str | None = None
    button_text: str | None = None
    sections: list[dict] | None = None
    buttons: list[dict] | None = None
    image_url: str | None = None
    caption: str | None = None


REQUIRED_SLOT_KEYS = ["occasion", "recipient_count", "budget_signal"]
ALL_SLOT_KEYS = ["occasion", "recipient_count", "budget_signal", "theme_preferences",
                 "branding_needed", "delivery_city", "delivery_timeline"]


class AgentState(TypedDict):
    whatsapp_number: str
    session_id: int
    stage: Stage
    messages: Annotated[list[AnyMessage], add_messages]
    slots: Slots
    missing_slots: list[str]
    last_question_asked: str | None
    candidates: list[dict]          # serialized CatalogHit dicts
    web_ideas: list[dict]           # serialized WebIdea dicts
    used_web_fallback: bool
    shortlist: list[RankedGift]
    pending_user_action: str | None
    refinement_request: str | None
    turn_outbound_messages: list[OutboundMessage]
    error: str | None
    # Within-turn routing signal: every node returns one, and the co-located `route_after_*`
    # function reads it back from state to pick the next edge. Must be a declared channel —
    # LangGraph drops/ignores writes to keys absent from the schema, and a node whose partial
    # update touches *only* this key would otherwise trip "must write to at least one of [...]".
    _route: str | None


def new_agent_state(whatsapp_number: str, session_id: int) -> AgentState:
    """A brand-new conversation's starting state — the "new gifting need" path."""
    return AgentState(
        whatsapp_number=whatsapp_number,
        session_id=session_id,
        stage="greeting",
        messages=[],
        slots=Slots(),
        missing_slots=list(ALL_SLOT_KEYS),
        last_question_asked=None,
        candidates=[],
        web_ideas=[],
        used_web_fallback=False,
        shortlist=[],
        pending_user_action=None,
        refinement_request=None,
        turn_outbound_messages=[],
        error=None,
        _route=None,
    )
