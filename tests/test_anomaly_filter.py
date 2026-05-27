"""Anomaly-filter unit tests."""

from __future__ import annotations

from typing import Any

from nengok.core.observer.anomaly_filter import AnomalyFilter
from nengok.core.types import AnomalySignal, TraceSpan


def _span(**overrides: Any) -> TraceSpan:
    defaults: dict[str, Any] = {
        "span_id": "s1",
        "trace_id": "t1",
        "name": "agent.respond",
        "status_code": "OK",
        "latency_ms": 100.0,
        "input_value": "hello",
        "output_value": "hi there",
        "attributes": {},
        "annotations": {},
    }
    defaults.update(overrides)
    return TraceSpan(**defaults)


def test_healthy_span_is_not_flagged() -> None:
    out = AnomalyFilter().filter([_span()])
    assert out == []


def test_error_status_is_flagged() -> None:
    out = AnomalyFilter().filter([_span(status_code="ERROR")])
    assert len(out) == 1
    assert AnomalySignal.ERROR_STATUS in out[0].signals


def test_high_latency_is_flagged() -> None:
    out = AnomalyFilter().filter([_span(latency_ms=999_999.0)])
    assert AnomalySignal.HIGH_LATENCY in out[0].signals


def test_missing_output_is_flagged() -> None:
    out = AnomalyFilter().filter([_span(output_value="   ")])
    assert AnomalySignal.MISSING_OUTPUT_FIELD in out[0].signals


def test_low_eval_score_via_annotation_dict_is_flagged() -> None:
    out = AnomalyFilter().filter([_span(annotations={"hallucination": {"score": 0.2, "label": "fail"}})])
    assert AnomalySignal.LOW_EVAL_SCORE in out[0].signals


def test_low_eval_score_via_plain_float_annotation_is_flagged() -> None:
    out = AnomalyFilter().filter([_span(annotations={"helpfulness": 0.1})])
    assert AnomalySignal.LOW_EVAL_SCORE in out[0].signals


def test_passing_eval_score_does_not_flag() -> None:
    out = AnomalyFilter().filter([_span(annotations={"hallucination": {"score": 0.95}, "helpfulness": 0.9})])
    assert out == []


def test_tool_failure_is_flagged_when_span_kind_is_tool_and_status_contains_error() -> None:
    out = AnomalyFilter().filter([_span(span_kind="TOOL", status_code="ERROR_RPC_TIMEOUT")])
    signals = out[0].signals
    assert AnomalySignal.TOOL_FAILURE in signals
    assert AnomalySignal.ERROR_STATUS in signals


def test_tool_span_with_ok_status_is_not_flagged_as_tool_failure() -> None:
    out = AnomalyFilter().filter([_span(span_kind="TOOL", status_code="OK")])
    assert out == []


def test_non_tool_span_with_error_status_is_not_flagged_as_tool_failure() -> None:
    out = AnomalyFilter().filter([_span(span_kind="LLM", status_code="ERROR")])
    signals = out[0].signals
    assert AnomalySignal.ERROR_STATUS in signals
    assert AnomalySignal.TOOL_FAILURE not in signals


def test_every_anomaly_signal_is_reachable_from_the_filter() -> None:
    """Smoke check that the filter knows how to emit every defined signal."""
    fired: set[AnomalySignal] = set()
    fired.update(AnomalyFilter().filter([_span(status_code="ERROR")])[0].signals)
    fired.update(AnomalyFilter().filter([_span(latency_ms=999_999.0)])[0].signals)
    fired.update(AnomalyFilter().filter([_span(output_value="")])[0].signals)
    fired.update(AnomalyFilter().filter([_span(annotations={"x": 0.1})])[0].signals)
    fired.update(AnomalyFilter().filter([_span(span_kind="TOOL", status_code="ERROR_TOOL")])[0].signals)

    assert fired == set(AnomalySignal)


def test_multiple_signals_can_attach_to_one_span() -> None:
    out = AnomalyFilter().filter(
        [
            _span(
                status_code="ERROR",
                latency_ms=999_999.0,
                output_value="",
                annotations={"helpfulness": 0.1},
            )
        ]
    )
    signals = set(out[0].signals)
    assert AnomalySignal.ERROR_STATUS in signals
    assert AnomalySignal.HIGH_LATENCY in signals
    assert AnomalySignal.MISSING_OUTPUT_FIELD in signals
    assert AnomalySignal.LOW_EVAL_SCORE in signals


def test_custom_thresholds_are_honored() -> None:
    strict = AnomalyFilter(latency_threshold_ms=50.0, low_eval_score=0.99)
    out = strict.filter([_span(latency_ms=100.0, annotations={"x": 0.98})])
    signals = set(out[0].signals)
    assert AnomalySignal.HIGH_LATENCY in signals
    assert AnomalySignal.LOW_EVAL_SCORE in signals


def test_empty_span_list_returns_empty() -> None:
    assert AnomalyFilter().filter([]) == []
