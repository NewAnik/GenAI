"""Shared structured-output Pydantic schemas used by multiple agent nodes.

Every place an LLM produces machine-consumed data uses `with_structured_output(...)` against
one of these — eliminating fragile prose/JSON parsing throughout the graph.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IntentLabel = Literal["new_request", "continue_slot_filling", "refinement",
                      "selection", "general_question", "smalltalk"]


class IntentClassification(BaseModel):
    intent: IntentLabel
    reason: str = Field(..., description="One short phrase explaining the classification")


AdjustmentType = Literal["cheaper", "pricier", "more_recipients", "fewer_recipients",
                         "theme_change", "branding_change", "more_options", "other"]


class RefinementIntent(BaseModel):
    adjustment_type: AdjustmentType
    updated_value: str | None = Field(
        None, description="Any new concrete value the user gave, e.g. '500', '200', 'eco-friendly'")
    notes: str = Field("", description="Brief free-text note on the requested adjustment")


SourceType = Literal["catalog_product", "catalog_gift_box", "web_idea"]
FitTag = Literal["budget_fit", "theme_fit", "occasion_fit", "branding_feasible",
                 "premium_pick", "value_pick", "external_idea"]


class CurationItem(BaseModel):
    rank: int
    source_type: SourceType
    ref_id: int | str = Field(..., description="The exact id/kind of a candidate as given — never invented")
    justification: str = Field(
        ..., description="1-2 sentences: why this fits — reference budget, theme, occasion, branding")
    fit_tags: list[FitTag] = Field(default_factory=list)


class CurationResult(BaseModel):
    items: list[CurationItem] = Field(..., min_length=1, max_length=5)
    overall_note: str | None = Field(
        None, description="Optional one-line framing for the whole shortlist")


class ContinuationChoice(BaseModel):
    wants_to_continue: bool
    notes: str = Field("", description="Brief note on what they said")
