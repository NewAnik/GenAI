"""Unit tests for the pure-Python slot-filling logic — no LLM, no DB. This is where the
"ask 1-2 trivial questions at a time, never re-ask, never hallucinate" guarantees live."""
from __future__ import annotations

from decimal import Decimal

from app.agent.slot_schema import (
    ExtractedSlots,
    compute_missing_slots,
    is_sufficient_for_search,
    merge_slots,
    next_question_slots,
)
from app.agent.state import Slots


def test_merge_slots_fills_only_empty_fields():
    existing = Slots(occasion="Diwali", recipient_count=50)
    extracted = ExtractedSlots(occasion="Onboarding", recipient_count=None, budget_per_recipient=500)

    merged = merge_slots(existing, extracted)

    assert merged.occasion == "Diwali"  # not overwritten
    assert merged.recipient_count == 50
    assert merged.budget_per_recipient == Decimal("500")


def test_merge_slots_derives_per_recipient_budget_from_total():
    existing = Slots(recipient_count=100)
    extracted = ExtractedSlots(total_budget=50000)

    merged = merge_slots(existing, extracted)

    assert merged.total_budget == Decimal("50000")
    assert merged.budget_per_recipient == Decimal("500.00")


def test_merge_slots_derives_total_from_per_recipient_budget():
    existing = Slots(recipient_count=20)
    extracted = ExtractedSlots(budget_per_recipient=750)

    merged = merge_slots(existing, extracted)

    assert merged.budget_per_recipient == Decimal("750")
    assert merged.total_budget == Decimal("15000.00")


def test_merge_slots_unions_theme_lists_case_insensitively():
    existing = Slots(theme_preferences=["Eco-friendly"])
    extracted = ExtractedSlots(theme_preferences=["eco-friendly", "Tech"])

    merged = merge_slots(existing, extracted)

    assert merged.theme_preferences == ["Eco-friendly", "Tech"]


def test_merge_slots_never_overwrites_without_explicit_flag():
    existing = Slots(budget_per_recipient=Decimal("1000"))
    extracted = ExtractedSlots(budget_per_recipient=200)

    merged = merge_slots(existing, extracted, allow_overwrite=False)

    assert merged.budget_per_recipient == Decimal("1000")


def test_merge_slots_overwrites_when_explicitly_allowed():
    existing = Slots(budget_per_recipient=Decimal("1000"), total_budget=Decimal("100000"))
    extracted = ExtractedSlots(budget_per_recipient=200)

    merged = merge_slots(existing, extracted, allow_overwrite=True)

    assert merged.budget_per_recipient == Decimal("200")


def test_compute_missing_slots_reports_budget_signal_once():
    slots = Slots(occasion="Diwali", recipient_count=10)
    missing = compute_missing_slots(slots)

    assert "budget_signal" in missing
    assert "budget_per_recipient" not in missing
    assert "total_budget" not in missing


def test_is_sufficient_for_search_requires_occasion_count_and_budget():
    assert not is_sufficient_for_search(Slots())
    assert not is_sufficient_for_search(Slots(occasion="Diwali", recipient_count=10))
    assert is_sufficient_for_search(
        Slots(occasion="Diwali", recipient_count=10, budget_per_recipient=Decimal("500"))
    )
    assert is_sufficient_for_search(
        Slots(occasion="Diwali", recipient_count=10, total_budget=Decimal("5000"))
    )


def test_next_question_slots_bundles_known_pairs():
    missing = ["recipient_count", "budget_signal", "theme_preferences"]
    keys, bundle = next_question_slots(missing)

    assert set(keys) == {"recipient_count", "budget_signal"}
    assert bundle is not None and "budget" in bundle.lower()


def test_next_question_slots_falls_back_to_single_question():
    missing = ["theme_preferences", "branding_needed"]
    keys, bundle = next_question_slots(missing)

    assert keys == ["theme_preferences"]
    assert bundle is None


def test_next_question_slots_returns_nothing_when_complete():
    assert next_question_slots([]) == ([], None)
