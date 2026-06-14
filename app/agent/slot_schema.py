"""Structured-output schema for LLM slot extraction, plus pure-Python merge/derivation logic.

Passing `ExtractedSlots` to `chat_model.with_structured_output(ExtractedSlots)` makes the LLM
return a validated Pydantic object via function-calling — no brittle prose/JSON parsing.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.agent.state import Slots


class ExtractedSlots(BaseModel):
    """Slots the LLM believes it can confidently extract from the latest user turn.

    The model is instructed to leave fields null if unstated and never hallucinate values —
    `merge_slots` only fills gaps, it never silently overwrites a confirmed value.
    """

    occasion: str | None = Field(
        None, description="Gifting occasion/event, e.g. Diwali, onboarding, work anniversary, "
                          "year-end appreciation, client appreciation")
    recipient_count: int | None = Field(None, description="Number of gift recipients")
    budget_per_recipient: float | None = Field(
        None, description="Budget per gift, in INR, if the user stated it per-person")
    total_budget: float | None = Field(
        None, description="Total campaign budget, in INR, if stated as a lump sum")
    theme_preferences: list[str] = Field(
        default_factory=list,
        description="Theme/interest keywords like tech, wellness, eco-friendly, gourmet, "
                    "premium, books, apparel, drinkware, stationery")
    branding_needed: bool | None = Field(
        None, description="Whether the user wants their company logo/branding on the gifts")
    delivery_city: str | None = Field(None, description="City/location for delivery")
    delivery_timeline: str | None = Field(
        None, description="When gifts are needed by, e.g. 'before Oct 20', 'in 3 weeks'")
    confidence_notes: str | None = Field(
        None, description="Brief note on any ambiguity worth flagging, "
                          "e.g. 'user said 50k total, unclear if per-person or total'")


# -- Question-asking strategy --------------------------------------------------------------

REQUIRED_FOR_SEARCH = ["occasion", "recipient_count", "budget_signal"]
NICE_TO_HAVE = ["theme_preferences", "branding_needed", "delivery_city", "delivery_timeline"]
SLOT_QUESTION_PRIORITY = [*REQUIRED_FOR_SEARCH, *NICE_TO_HAVE]

# Safe pairs of trivial slots that can be bundled into a single natural question.
BUNDLE_QUESTIONS: dict[frozenset[str], str] = {
    frozenset({"recipient_count", "budget_signal"}):
        "How many people are you gifting, and what's your rough budget per person (or total)?",
    frozenset({"delivery_city", "delivery_timeline"}):
        "Which city should we plan delivery to, and by when do you need these?",
}

SLOT_DESCRIPTIONS: dict[str, str] = {
    "occasion": "the occasion or event you're gifting for",
    "recipient_count": "roughly how many people you're gifting to",
    "budget_signal": "your budget — either per gift or a total amount",
    "theme_preferences": "any theme or vibe you have in mind (e.g. eco-friendly, tech, premium, gourmet)",
    "branding_needed": "whether you'd like your company logo/branding on the gifts",
    "delivery_city": "which city the gifts should be delivered to",
    "delivery_timeline": "when you need the gifts by",
}


def compute_missing_slots(slots: Slots) -> list[str]:
    missing: list[str] = []
    for key in SLOT_QUESTION_PRIORITY:
        if key == "budget_signal":
            if not slots.has_budget_signal():
                missing.append(key)
        elif key == "theme_preferences":
            if not slots.theme_preferences:
                missing.append(key)
        else:
            if getattr(slots, key) is None:
                missing.append(key)
    return missing


def is_sufficient_for_search(slots: Slots) -> bool:
    return slots.occasion is not None and slots.recipient_count is not None and slots.has_budget_signal()


def merge_slots(existing: Slots, extracted: ExtractedSlots, *, allow_overwrite: bool = False) -> Slots:
    """Fill empty fields from `extracted`; union theme lists; derive cross-fields.

    `allow_overwrite=True` is set by the caller only when `route_intent`/`handle_refinement`
    has classified this turn as an explicit correction (e.g. "actually, budget is 1000 not 800")
    — `merge_slots` itself never guesses whether an overwrite is appropriate.
    """
    data = existing.model_dump()

    def _maybe_set(key: str, value):
        if value is None:
            return
        if allow_overwrite or data.get(key) is None:
            data[key] = value

    _maybe_set("occasion", extracted.occasion)
    _maybe_set("recipient_count", extracted.recipient_count)
    if extracted.budget_per_recipient is not None:
        _maybe_set("budget_per_recipient", Decimal(str(extracted.budget_per_recipient)))
    if extracted.total_budget is not None:
        _maybe_set("total_budget", Decimal(str(extracted.total_budget)))
    _maybe_set("branding_needed", extracted.branding_needed)
    _maybe_set("delivery_city", extracted.delivery_city)
    _maybe_set("delivery_timeline", extracted.delivery_timeline)

    if extracted.theme_preferences:
        seen = {t.lower() for t in data["theme_preferences"]}
        for theme in extracted.theme_preferences:
            if theme.lower() not in seen:
                data["theme_preferences"].append(theme)
                seen.add(theme.lower())

    merged = Slots.model_validate(data)
    return _derive_cross_fields(merged)


def _derive_cross_fields(slots: Slots) -> Slots:
    """Pure-Python arithmetic — never delegated to the LLM."""
    if slots.budget_per_recipient is None and slots.total_budget is not None and slots.recipient_count:
        slots = slots.model_copy(update={
            "budget_per_recipient": (slots.total_budget / slots.recipient_count).quantize(Decimal("0.01"))
        })
    elif slots.total_budget is None and slots.budget_per_recipient is not None and slots.recipient_count:
        slots = slots.model_copy(update={
            "total_budget": (slots.budget_per_recipient * slots.recipient_count).quantize(Decimal("0.01"))
        })
    return slots


def next_question_slots(missing: list[str]) -> tuple[list[str], str | None]:
    """Pick the next 1-2 slots to ask about (by priority), and a bundle template if applicable.

    Returns (slot_keys_to_ask, bundle_template_or_None).
    """
    if not missing:
        return [], None
    ordered = [k for k in SLOT_QUESTION_PRIORITY if k in missing]
    if len(ordered) >= 2:
        pair = frozenset(ordered[:2])
        if pair in BUNDLE_QUESTIONS:
            return ordered[:2], BUNDLE_QUESTIONS[pair]
    return ordered[:1], None
