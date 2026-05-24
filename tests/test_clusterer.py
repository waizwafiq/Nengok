"""Clusterer unit tests with a fake Gemini callable."""

from __future__ import annotations

import json
from typing import Any

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import (
    MAX_CLUSTER_NAME_LENGTH,
    Clusterer,
    _normalize_name,
    _trim,
)
from nengok.core.types import AnomalousSpan, AnomalySignal, TraceSpan


def _anomaly(span_id: str, **span_overrides: Any) -> AnomalousSpan:
    defaults: dict[str, Any] = {
        "span_id": span_id,
        "trace_id": f"trace-{span_id}",
        "name": "agent.respond",
        "status_code": "ERROR",
        "latency_ms": 200.0,
        "input_value": "hello",
        "output_value": "broken",
        "attributes": {},
        "annotations": {},
    }
    defaults.update(span_overrides)
    return AnomalousSpan(span=TraceSpan(**defaults), signals=[AnomalySignal.ERROR_STATUS])


def _fake_response(groups: list[dict[str, Any]]) -> str:
    return json.dumps({"clusters": groups})


def test_normalize_name_handles_kebab_lowercase_and_length() -> None:
    assert _normalize_name("Schema Drift  on Flights!") == "schema-drift-on-flights"
    assert _normalize_name("UPPER___snake") == "upper-snake"
    long = "x" * 60
    out = _normalize_name(long)
    assert len(out) <= MAX_CLUSTER_NAME_LENGTH
    assert out == "x" * MAX_CLUSTER_NAME_LENGTH


def test_normalize_name_empty_falls_back() -> None:
    assert _normalize_name("!!!  ") == "unnamed-cluster"
    assert _normalize_name("") == "unnamed-cluster"


def test_trim_respects_budget() -> None:
    assert _trim(None, 100) == ""
    assert _trim("short", 100) == "short"
    trimmed = _trim("x" * 50, 10)
    assert trimmed.startswith("x" * 10)
    assert trimmed.endswith("<truncated>")


def test_cluster_groups_members_and_picks_exemplars(tmp_config: NengokConfig) -> None:
    anomalies = [_anomaly(f"s{i}") for i in range(7)]

    fake_groups = [
        {
            "name": "Schema Drift!",
            "description": "Flights tool drifted from contract.",
            "member_span_ids": [f"s{i}" for i in range(6)],
        },
        {
            "name": "hotels timeout",
            "description": "Hotels API timing out.",
            "member_span_ids": ["s6"],
        },
    ]

    def fake_gemini(_prompt: str) -> str:
        return _fake_response(fake_groups)

    clusters = Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster(anomalies)

    assert [c.name for c in clusters] == ["schema-drift", "hotels-timeout"]
    assert len(clusters[0].member_span_ids) == 6
    assert len(clusters[0].exemplar_span_ids) == 5
    assert clusters[0].exemplar_span_ids == [f"s{i}" for i in range(5)]
    assert clusters[1].exemplar_span_ids == ["s6"]


def test_cluster_skips_groups_with_unknown_span_ids(tmp_config: NengokConfig) -> None:
    anomalies = [_anomaly("s1"), _anomaly("s2")]

    fake_groups = [
        {
            "name": "ghost-cluster",
            "description": "Refers to span ids the local batch never produced.",
            "member_span_ids": ["s99"],
        },
        {
            "name": "real-cluster",
            "description": "Real members.",
            "member_span_ids": ["s1", "s2"],
        },
    ]

    def fake_gemini(_prompt: str) -> str:
        return _fake_response(fake_groups)

    clusters = Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster(anomalies)
    assert [c.name for c in clusters] == ["real-cluster"]


def test_cluster_accepts_code_fenced_json(tmp_config: NengokConfig) -> None:
    anomalies = [_anomaly("s1")]

    def fake_gemini(_prompt: str) -> str:
        payload = _fake_response(
            [{"name": "weather-units", "description": "F vs C.", "member_span_ids": ["s1"]}]
        )
        return f"```json\n{payload}\n```"

    clusters = Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster(anomalies)
    assert len(clusters) == 1
    assert clusters[0].name == "weather-units"


def test_prompt_includes_trimmed_trace_bodies(tmp_config: NengokConfig) -> None:
    long_input = "A" * 5000
    anomalies = [_anomaly("s1", input_value=long_input, output_value="ok")]

    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return _fake_response([{"name": "one", "description": "d", "member_span_ids": ["s1"]}])

    Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster(anomalies)

    budget = tmp_config.cluster_trace_char_budget
    assert "A" * budget in captured["prompt"]
    assert "A" * (budget + 1) not in captured["prompt"]
    assert "<truncated>" in captured["prompt"]


def test_cluster_returns_empty_when_no_anomalies(tmp_config: NengokConfig) -> None:
    called = False

    def fake_gemini(_prompt: str) -> str:
        nonlocal called
        called = True
        return _fake_response([])

    clusters = Clusterer(config=tmp_config, gemini_call=fake_gemini).cluster([])
    assert clusters == []
    assert called is False
