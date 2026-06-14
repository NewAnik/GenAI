"""Discovers every YAML conversation fixture under `fixtures/` and runs it through the scripted
runner — one parametrized test per fixture file, named after the fixture, so a broken conversation
shape points straight at the YAML that encodes it."""
from __future__ import annotations

import pytest

from tests.scripted_conversations.runner import iter_fixture_paths, load_fixture, run_fixture

_FIXTURE_PATHS = iter_fixture_paths()

assert _FIXTURE_PATHS, "expected at least one *.yaml fixture under tests/scripted_conversations/fixtures/"


@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=[p.stem for p in _FIXTURE_PATHS])
async def test_scripted_conversation(fixture_path):
    fixture = load_fixture(fixture_path)

    run = await run_fixture(fixture)

    assert run.final_state["stage"] == "done"
    assert run.recommendation_log, "expected at least one recommendation_logs audit row"
    assert run.recommendation_log[-1][1]["event"] == "selection_confirmed"
