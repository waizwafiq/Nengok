"""Hypothesizer unit tests with a fake Gemini callable."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from nengok.config import NengokConfig
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.types import Cluster, ClusterStatus, TraceSpan


def _cluster(exemplar_ids: list[str]) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id="c-1",
        name="schema-drift-on-flights",
        description="Flights tool drifted from contract.",
        status=ClusterStatus.OPEN,
        member_span_ids=exemplar_ids,
        exemplar_span_ids=exemplar_ids,
        hypothesis=None,
        created_at=now,
        updated_at=now,
    )


def _span(span_id: str, **overrides: Any) -> TraceSpan:
    defaults: dict[str, Any] = {
        "span_id": span_id,
        "trace_id": f"trace-{span_id}",
        "name": "tool.flights.search",
        "status_code": "OK",
        "latency_ms": 200.0,
        "input_value": "departure=SFO",
        "output_value": "departure_time=2025-01-01",
        "attributes": {"openinference.span.kind": "TOOL"},
        "annotations": {},
    }
    defaults.update(overrides)
    return TraceSpan(**defaults)


class _FakePhoenix:
    def __init__(self, spans: list[TraceSpan]) -> None:
        self._spans = spans
        self.calls: list[dict[str, Any]] = []

    def get_spans_by_ids(
        self,
        *,
        project_identifier: str,
        span_ids: Any,
        limit: int = 1000,
    ) -> list[TraceSpan]:
        self.calls.append(
            {"project_identifier": project_identifier, "span_ids": list(span_ids), "limit": limit}
        )
        wanted = set(span_ids)
        return [s for s in self._spans if s.span_id in wanted]


def _hypothesis_json(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "summary": "Flights tool returns departure_time as a UNIX epoch int.",
        "expected_behavior": "departure_time is an ISO-8601 string.",
        "actual_behavior": "departure_time arrives as an integer.",
        "likely_cause": "flights.search v3 changed the contract without a version bump.",
        "implicated_tools": ["tool.flights.search"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_hypothesize_parses_gemini_response(tmp_config: NengokConfig) -> None:
    spans = [_span("s1"), _span("s2")]
    phoenix = _FakePhoenix(spans)

    def fake_gemini(_prompt: str) -> str:
        return _hypothesis_json()

    hypothesizer = Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini)
    result = hypothesizer.hypothesize(_cluster(["s1", "s2"]))

    assert result.summary.startswith("Flights tool")
    assert result.expected_behavior
    assert result.actual_behavior
    assert result.likely_cause
    assert result.implicated_tools == ["tool.flights.search"]
    assert isinstance(result.implicated_tools, list)


def test_hypothesize_fetches_exemplars_through_phoenix(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1"), _span("s2")])

    def fake_gemini(_prompt: str) -> str:
        return _hypothesis_json()

    Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
        _cluster(["s1", "s2"])
    )

    assert phoenix.calls == [
        {
            "project_identifier": tmp_config.project_identifier,
            "span_ids": ["s1", "s2"],
            "limit": 1000,
        }
    ]


def test_hypothesize_includes_current_prompt_in_gemini_call(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1")])
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return _hypothesis_json()

    Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
        _cluster(["s1"]),
        current_prompt="Be concise. Always return ISO-8601 times.",
    )

    assert "Always return ISO-8601 times." in captured["prompt"]
    assert "schema-drift-on-flights" in captured["prompt"]


def test_hypothesize_marks_missing_exemplars(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1")])
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return _hypothesis_json()

    Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
        _cluster(["s1", "s-missing"])
    )

    assert "exemplar not retrievable from Phoenix" in captured["prompt"]


def test_hypothesize_retries_once_on_invalid_json(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1")])
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "this is not json"
        return _hypothesis_json()

    result = Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
        _cluster(["s1"])
    )

    assert calls["n"] == 2
    assert result.implicated_tools == ["tool.flights.search"]


def test_hypothesize_propagates_validation_error_after_retry(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1")])

    def fake_gemini(_prompt: str) -> str:
        return "still not json"

    with pytest.raises(ValidationError):
        Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
            _cluster(["s1"])
        )


def test_hypothesize_handles_code_fenced_json(tmp_config: NengokConfig) -> None:
    phoenix = _FakePhoenix([_span("s1")])

    def fake_gemini(_prompt: str) -> str:
        return f"```json\n{_hypothesis_json()}\n```"

    result = Hypothesizer(config=tmp_config, phoenix=phoenix, gemini_call=fake_gemini).hypothesize(
        _cluster(["s1"])
    )

    assert result.implicated_tools == ["tool.flights.search"]


def test_hypothesize_without_phoenix_skips_exemplar_fetch(tmp_config: NengokConfig) -> None:
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return _hypothesis_json(implicated_tools=[])

    result = Hypothesizer(config=tmp_config, gemini_call=fake_gemini).hypothesize(_cluster(["s1", "s2"]))

    assert result.implicated_tools == []
    assert "exemplar not retrievable from Phoenix" in captured["prompt"]
