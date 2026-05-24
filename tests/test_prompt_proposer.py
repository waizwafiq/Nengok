"""PromptProposer unit tests with a fake Gemini callable."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nengok.config import NengokConfig
from nengok.core.fixer.prompt_proposer import (
    MAX_PROPOSER_EXEMPLARS,
    SAMPLE_AGENT_PROJECT,
    PromptProposer,
)
from nengok.core.types import (
    Cluster,
    ClusterStatus,
    RootCauseHypothesis,
    TraceSpan,
)


def _cluster(exemplar_ids: list[str], *, with_hypothesis: bool = True) -> Cluster:
    now = datetime.now(UTC)
    hypothesis = (
        RootCauseHypothesis(
            summary="Flights tool returns departure_time as integer.",
            expected_behavior="ISO-8601 string.",
            actual_behavior="UNIX epoch integer.",
            likely_cause="flights.search v3 contract drift.",
            implicated_tools=["tool.flights.search"],
        )
        if with_hypothesis
        else None
    )
    return Cluster(
        cluster_id="c-1",
        name="schema-drift-on-flights",
        description="Flights tool drifted from contract.",
        status=ClusterStatus.DIAGNOSED,
        member_span_ids=exemplar_ids,
        exemplar_span_ids=exemplar_ids,
        hypothesis=hypothesis,
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
        "input_value": f"in-{span_id}",
        "output_value": f"out-{span_id}",
        "attributes": {},
        "annotations": {},
    }
    defaults.update(overrides)
    return TraceSpan(**defaults)


class _FakePhoenix:
    def __init__(
        self,
        *,
        spans: list[TraceSpan] | None = None,
        prompt_versions: dict[str, str] | None = None,
    ) -> None:
        self._spans = spans or []
        self._prompts = prompt_versions or {}
        self.span_calls: list[dict[str, Any]] = []
        self.prompt_calls: list[str] = []

    def get_spans_by_ids(
        self,
        *,
        project_identifier: str,
        span_ids: Any,
        limit: int = 1000,
    ) -> list[TraceSpan]:
        self.span_calls.append(
            {"project_identifier": project_identifier, "span_ids": list(span_ids), "limit": limit}
        )
        wanted = set(span_ids)
        return [s for s in self._spans if s.span_id in wanted]

    def get_prompt_version(self, *, name: str) -> str | None:
        self.prompt_calls.append(name)
        return self._prompts.get(name)


def _proposal_json(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "proposed_prompt": "BASELINE\n\n# Guardrail: departure_time must be a string.",
        "rationale": "Added explicit type guardrail for departure_time.",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_propose_returns_proposal_with_diff_and_rationale(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    phoenix = _FakePhoenix(spans=[_span("s1"), _span("s2")])

    def fake_gemini(_prompt: str) -> str:
        return _proposal_json()

    proposal = PromptProposer(config=sample_config, phoenix=phoenix, gemini_call=fake_gemini).propose(
        _cluster(["s1", "s2"])
    )

    assert proposal.cluster_id == "c-1"
    assert proposal.baseline_prompt.startswith("# Travel Planner")
    assert proposal.proposed_prompt != proposal.baseline_prompt
    assert "departure_time" in proposal.proposed_prompt
    assert proposal.rationale.strip()


def test_load_baseline_prefers_sample_agent_file(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    phoenix = _FakePhoenix(prompt_versions={SAMPLE_AGENT_PROJECT: "PHOENIX-VERSION"})
    proposer = PromptProposer(config=sample_config, phoenix=phoenix)

    baseline = proposer.load_baseline_prompt()

    assert baseline.startswith("# Travel Planner")
    assert phoenix.prompt_calls == []


def test_load_baseline_falls_back_to_phoenix_prompt_management(tmp_config: NengokConfig) -> None:
    other_config = replace(tmp_config, project_identifier="some-other-agent")
    phoenix = _FakePhoenix(prompt_versions={"some-other-agent": "PHOENIX-PROMPT-V7"})
    proposer = PromptProposer(config=other_config, phoenix=phoenix)

    baseline = proposer.load_baseline_prompt()

    assert baseline == "PHOENIX-PROMPT-V7"
    assert phoenix.prompt_calls == ["some-other-agent"]


def test_load_baseline_falls_back_to_config_path(tmp_config: NengokConfig, tmp_path: Path) -> None:
    prompt_file = tmp_path / "my_prompt.md"
    prompt_file.write_text("FROM-DISK", encoding="utf-8")
    config = replace(
        tmp_config,
        project_identifier="some-other-agent",
        baseline_prompt_path=prompt_file,
    )
    phoenix = _FakePhoenix(prompt_versions={})

    baseline = PromptProposer(config=config, phoenix=phoenix).load_baseline_prompt()

    assert baseline == "FROM-DISK"


def test_load_baseline_raises_when_no_source_available(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, project_identifier="unknown-agent")
    proposer = PromptProposer(config=config)

    with pytest.raises(RuntimeError, match="No baseline prompt"):
        proposer.load_baseline_prompt()


def test_proposer_prompt_includes_hypothesis_and_exemplars(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    spans = [_span(f"s{i}", input_value=f"INPUT-{i}", output_value=f"OUTPUT-{i}") for i in range(5)]
    phoenix = _FakePhoenix(spans=spans)
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        return _proposal_json()

    PromptProposer(config=sample_config, phoenix=phoenix, gemini_call=fake_gemini).propose(
        _cluster([f"s{i}" for i in range(5)])
    )

    text = captured["prompt"]
    assert "flights.search v3 contract drift." in text
    assert "INPUT-0" in text and "INPUT-1" in text and "INPUT-2" in text
    assert "INPUT-3" not in text
    assert phoenix.span_calls[0]["span_ids"] == ["s0", "s1", "s2"]
    assert MAX_PROPOSER_EXEMPLARS == 3


def test_proposer_retries_once_on_invalid_json(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)
    calls = {"n": 0}

    def fake_gemini(_prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "definitely not json"
        return _proposal_json()

    proposal = PromptProposer(config=sample_config, gemini_call=fake_gemini).propose(_cluster(["s1"]))

    assert calls["n"] == 2
    assert proposal.rationale.strip()


def test_proposer_propagates_validation_error_after_retry(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)

    def fake_gemini(_prompt: str) -> str:
        return "still not json"

    with pytest.raises(ValidationError):
        PromptProposer(config=sample_config, gemini_call=fake_gemini).propose(_cluster(["s1"]))


def test_proposer_handles_code_fenced_json(tmp_config: NengokConfig) -> None:
    sample_config = replace(tmp_config, project_identifier=SAMPLE_AGENT_PROJECT)

    def fake_gemini(_prompt: str) -> str:
        return f"```json\n{_proposal_json()}\n```"

    proposal = PromptProposer(config=sample_config, gemini_call=fake_gemini).propose(_cluster(["s1"]))

    assert proposal.proposed_prompt != proposal.baseline_prompt
