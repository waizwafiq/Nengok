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
