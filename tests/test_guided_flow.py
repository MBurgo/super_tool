from __future__ import annotations

from typing import List

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from core.guided_flow import (
    GuidedFlowState,
    TrendPayload,
    FocusTestIteration,
    discover_trends,
    choose_theme,
    generate_variants,
    begin_focus_testing,
    execute_focus_testing,
)


def test_discover_trends_initialises_state():
    state = GuidedFlowState()

    def fake_fetch():
        return (
            [{"query": "AI chips", "value": 90}],
            [{"title": "Semiconductor rally continues"}],
        )

    payload = discover_trends(state, fake_fetch)

    assert isinstance(payload, TrendPayload)
    assert state.stage == "choose_theme"
    assert payload.themes[0].startswith("AI chips")
    assert state.trends is payload


def test_choose_theme_and_generate_variants():
    state = GuidedFlowState()

    discover_trends(state, lambda: ([{"query": "AI", "value": 100}], []))
    choose_theme(state, "AI — 100")

    created = generate_variants(state, lambda: ["Variant A", "Variant B"])

    assert state.stage == "draft_variants"
    assert created == ["Variant A", "Variant B"]
    assert state.variants == created


def test_begin_focus_testing_sets_stage_and_source():
    state = GuidedFlowState()
    discover_trends(state, lambda: ([{"query": "AI", "value": 100}], []))
    choose_theme(state, "AI — 100")
    generate_variants(state, lambda: ["Variant A"])

    begin_focus_testing(state, "Variant A")

    assert state.stage == "focus_test"
    assert state.focus_source == "Variant A"


def test_execute_focus_testing_passes_with_improvement():
    state = GuidedFlowState()
    discover_trends(state, lambda: ([{"query": "AI", "value": 100}], []))
    choose_theme(state, "AI — 100")
    generate_variants(state, lambda: ["Variant A"])
    begin_focus_testing(state, "Variant A")

    history: List[str] = []

    def tester(copy: str, round_idx: int) -> FocusTestIteration:
        score = 0.4 if round_idx == 1 else 0.85
        history.append(copy)
        return FocusTestIteration(
            round=round_idx,
            copy=copy,
            summary=f"Round {round_idx}",
            mean_intent=score,
        )

    def improver(copy: str, iteration: FocusTestIteration) -> str:
        return copy + " ++"

    outcome = execute_focus_testing(
        state,
        tester,
        improver,
        threshold=0.8,
        max_rounds=3,
    )

    assert state.stage == "complete"
    assert outcome.passed is True
    assert len(outcome.iterations) == 2
    assert history == ["Variant A", "Variant A ++"]
    assert outcome.final_copy == "Variant A ++"


def test_execute_focus_testing_handles_failure_after_max_rounds():
    state = GuidedFlowState()
    discover_trends(state, lambda: ([{"query": "AI", "value": 100}], []))
    choose_theme(state, "AI — 100")
    generate_variants(state, lambda: ["Variant A"])
    begin_focus_testing(state, "Variant A")

    def tester(copy: str, round_idx: int) -> FocusTestIteration:
        return FocusTestIteration(
            round=round_idx,
            copy=copy,
            summary="Needs work",
            mean_intent=0.3,
        )

    def improver(copy: str, iteration: FocusTestIteration) -> str:
        return copy + f" ({iteration.round})"

    outcome = execute_focus_testing(
        state,
        tester,
        improver,
        threshold=0.6,
        max_rounds=2,
    )

    assert outcome.passed is False
    assert len(outcome.iterations) == 2
    assert outcome.final_copy == outcome.iterations[-1].copy


def test_execute_focus_testing_requires_preparation():
    state = GuidedFlowState()

    with pytest.raises(ValueError):
        execute_focus_testing(
            state,
            lambda copy, i: FocusTestIteration(i, copy, "", 0.0),
            lambda copy, iteration: copy,
            threshold=0.5,
            max_rounds=1,
        )

