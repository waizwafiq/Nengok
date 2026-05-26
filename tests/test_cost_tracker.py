"""Unit coverage for the per-cycle Gemini cost tracker."""

from __future__ import annotations

import pytest

from nengok.core.cost import CostTracker


def test_record_accumulates_tokens() -> None:
    tracker = CostTracker()
    tracker.record(prompt_tokens=100, completion_tokens=50)
    tracker.record(prompt_tokens=200, completion_tokens=25)

    assert tracker.prompt_tokens == 300
    assert tracker.completion_tokens == 75
    assert tracker.tokens_used == 375


def test_dollars_used_applies_separate_rates() -> None:
    tracker = CostTracker(
        input_dollars_per_million=2.0,
        output_dollars_per_million=10.0,
    )
    tracker.record(prompt_tokens=1_000_000, completion_tokens=500_000)

    assert tracker.dollars_used == pytest.approx(2.0 + 5.0)


def test_reset_zeros_totals() -> None:
    tracker = CostTracker()
    tracker.record(prompt_tokens=10, completion_tokens=10)
    tracker.reset()

    assert tracker.tokens_used == 0
    assert tracker.dollars_used == 0.0


def test_is_over_budget_compares_against_limit() -> None:
    tracker = CostTracker()
    tracker.record(prompt_tokens=300, completion_tokens=200)

    assert tracker.is_over_budget(limit_tokens=400)
    assert not tracker.is_over_budget(limit_tokens=600)


def test_zero_limit_disables_check() -> None:
    tracker = CostTracker()
    tracker.record(prompt_tokens=10_000_000, completion_tokens=10_000_000)

    assert not tracker.is_over_budget(limit_tokens=0)


def test_negative_tokens_raise() -> None:
    tracker = CostTracker()
    with pytest.raises(ValueError):
        tracker.record(prompt_tokens=-1, completion_tokens=0)
