"""TestGenerator unit tests with a fake Gemini callable."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from nengok.config import NengokConfig
from nengok.core.fixer.test_generator import (
    MAX_REGRESSION_CASES,
    MIN_REGRESSION_CASES,
    TestGenerator,
)
from nengok.core.types import Cluster, ClusterStatus, RootCauseHypothesis


def _cluster() -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id="c-1",
        name="schema-drift-on-flights",
        description="Flights tool drifted from contract.",
        status=ClusterStatus.DIAGNOSED,
        member_span_ids=["s1", "s2"],
        exemplar_span_ids=["s1"],
        hypothesis=RootCauseHypothesis(
            summary="Drift in departure_time type.",
            expected_behavior="ISO-8601 string.",
            actual_behavior="UNIX epoch int.",
            likely_cause="flights v3 contract change.",
            implicated_tools=["tool.flights.search"],
        ),
        created_at=now,
        updated_at=now,
    )


def _case(index: int) -> dict[str, Any]:
    return {
        "input": {"query": f"plan trip {index}"},
        "expected": {"departure_time_is_string": True},
        "metadata": {"variation": index},
    }


def _cases_json(count: int) -> str:
    return json.dumps({"cases": [_case(i) for i in range(count)]})


def test_generate_returns_pydantic_cases(tmp_config: NengokConfig) -> None:
    def fake_gemini(_prompt: str) -> str:
        return _cases_json(6)

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert len(cases) == 6
    for case in cases:
        assert case.case_id
        assert "query" in case.input
        assert case.expected == {"departure_time_is_string": True}


def test_generate_caps_at_maximum(tmp_config: NengokConfig) -> None:
    def fake_gemini(_prompt: str) -> str:
        return _cases_json(MAX_REGRESSION_CASES + 10)

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert len(cases) == MAX_REGRESSION_CASES


def test_generate_retries_when_below_minimum(tmp_config: NengokConfig) -> None:
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return _cases_json(2)
        return _cases_json(MIN_REGRESSION_CASES + 1)

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert calls["n"] == 2
    assert len(cases) == MIN_REGRESSION_CASES + 1


def test_generate_proceeds_when_retry_still_short(
    tmp_config: NengokConfig, caplog: pytest.LogCaptureFixture
) -> None:
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return _cases_json(2)
        return _cases_json(3)

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert calls["n"] == 2
    assert len(cases) == 3
    assert any("still under minimum" in record.message for record in caplog.records)


def test_generate_does_not_retry_when_first_batch_meets_minimum(
    tmp_config: NengokConfig,
) -> None:
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        return _cases_json(MIN_REGRESSION_CASES)

    TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert calls["n"] == 1


def test_generate_metadata_includes_audit_fields(tmp_config: NengokConfig) -> None:
    def fake_gemini(_prompt: str) -> str:
        return _cases_json(MIN_REGRESSION_CASES)

    cluster = _cluster()
    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(cluster)

    for case in cases:
        assert case.metadata["cluster_id"] == cluster.cluster_id
        assert case.metadata["cluster_name"] == cluster.name
        assert case.metadata["failure_signal"] == cluster.name
        assert case.metadata["generator_model"] == tmp_config.diagnoser_model
        assert case.metadata["variation"] in range(MIN_REGRESSION_CASES)


def test_generate_raises_on_unparsable_json(tmp_config: NengokConfig) -> None:
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        return "not json"

    with pytest.raises(ValidationError):
        TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())
    assert calls["n"] == 2, "expected one retry before propagating ValidationError"


def test_generate_retries_on_validation_error_then_succeeds(
    tmp_config: NengokConfig, caplog: pytest.LogCaptureFixture
) -> None:
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return _cases_json(MIN_REGRESSION_CASES)

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert calls["n"] == 2
    assert len(cases) == MIN_REGRESSION_CASES
    assert any("failed validation" in record.message for record in caplog.records)


def test_generate_handles_code_fenced_json(tmp_config: NengokConfig) -> None:
    def fake_gemini(_prompt: str) -> str:
        return f"```json\n{_cases_json(MIN_REGRESSION_CASES)}\n```"

    cases = TestGenerator(config=tmp_config, gemini_call=fake_gemini).generate(_cluster())

    assert len(cases) == MIN_REGRESSION_CASES
