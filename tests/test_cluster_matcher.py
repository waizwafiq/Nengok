"""ClusterMatcher unit tests with a fake judge throughout."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from nengok.config import NengokConfig
from nengok.core.diagnoser.matcher import ClusterMatcher
from nengok.core.types import Cluster, ClusterStatus, RootCauseHypothesis


def _cluster(
    cluster_id: str,
    name: str,
    *,
    signals: list[str] | None = None,
    summary: str | None = None,
) -> Cluster:
    now = datetime.now(UTC)
    hypothesis = None
    if summary is not None:
        hypothesis = RootCauseHypothesis(
            summary=summary,
            expected_behavior="e",
            actual_behavior="a",
            likely_cause="c",
        )
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        description=f"description for {name}",
        status=ClusterStatus.OPEN,
        member_span_ids=[f"s-{cluster_id}"],
        exemplar_span_ids=[f"s-{cluster_id}"],
        hypothesis=hypothesis,
        created_at=now,
        updated_at=now,
        signals=signals or [],
    )


def _verdict(same_failure: bool, confidence: float) -> str:
    return json.dumps({"same_failure": same_failure, "confidence": confidence})


def test_exact_name_match_skips_the_judge(tmp_config: NengokConfig) -> None:
    calls: list[str] = []

    def fake_judge(prompt: str) -> str:
        calls.append(prompt)
        return _verdict(True, 1.0)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "flights-schema-drift", signals=["error_status"])
    existing = [_cluster("old", "flights-schema-drift", signals=["error_status"])]

    assert matcher.match(candidate, existing) == "old"
    assert calls == []


def test_judge_confirms_near_miss_with_shared_signal(tmp_config: NengokConfig) -> None:
    def fake_judge(_prompt: str) -> str:
        return _verdict(True, 0.92)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "flight-departure-schema-drift", signals=["error_status"])
    existing = [_cluster("old", "flights-schema-drift", signals=["error_status", "tool_failure"])]

    assert matcher.match(candidate, existing) == "old"


def test_below_threshold_confidence_is_rejected(tmp_config: NengokConfig) -> None:
    def fake_judge(_prompt: str) -> str:
        return _verdict(True, 0.5)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "flight-departure-schema-drift", signals=["error_status"])
    existing = [_cluster("old", "flights-schema-drift", signals=["error_status"])]

    assert matcher.match(candidate, existing) is None


def test_judge_denial_is_rejected(tmp_config: NengokConfig) -> None:
    def fake_judge(_prompt: str) -> str:
        return _verdict(False, 0.95)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "weather-unit-mismatch", signals=["missing_output_field"])
    existing = [_cluster("old", "weather-format-confusion", signals=["missing_output_field"])]

    assert matcher.match(candidate, existing) is None


def test_no_shared_signal_means_no_judge_call(tmp_config: NengokConfig) -> None:
    calls: list[str] = []

    def fake_judge(prompt: str) -> str:
        calls.append(prompt)
        return _verdict(True, 1.0)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "hotels-timeout", signals=["high_latency"])
    existing = [_cluster("old", "flights-schema-drift", signals=["error_status"])]

    assert matcher.match(candidate, existing) is None
    assert calls == []


def test_invalid_judge_payload_is_treated_as_no_match(tmp_config: NengokConfig) -> None:
    def fake_judge(_prompt: str) -> str:
        return "not json"

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster("new", "hotels-slow", signals=["high_latency"])
    existing = [_cluster("old", "hotels-timeout", signals=["high_latency"])]

    assert matcher.match(candidate, existing) is None


def test_prompt_carries_names_descriptions_and_summaries(tmp_config: NengokConfig) -> None:
    captured: dict[str, str] = {}

    def fake_judge(prompt: str) -> str:
        captured["prompt"] = prompt
        return _verdict(True, 0.9)

    matcher = ClusterMatcher(config=tmp_config, gemini_call=fake_judge)
    candidate = _cluster(
        "new", "flight-departure-drift", signals=["error_status"], summary="departure_time is an int"
    )
    existing = [
        _cluster("old", "flights-schema-drift", signals=["error_status"], summary="epoch instead of ISO")
    ]

    matcher.match(candidate, existing)

    assert "flight-departure-drift" in captured["prompt"]
    assert "flights-schema-drift" in captured["prompt"]
    assert "departure_time is an int" in captured["prompt"]
    assert "epoch instead of ISO" in captured["prompt"]
