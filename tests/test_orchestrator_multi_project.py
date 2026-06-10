"""
Per-project observer and diagnoser loop.

A fake Phoenix returns distinct spans per project; the cycle covers
both projects, stamps each cluster row with its project, and records
the project list on the cycle row.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core import orchestrator as orch_module
from nengok.core.diagnoser.hypothesizer import Hypothesizer
from nengok.core.fixer.prompt_proposer import PromptProposer
from nengok.core.fixer.test_generator import MIN_REGRESSION_CASES, TestGenerator
from nengok.core.orchestrator import Orchestrator
from nengok.core.types import (
    AnomalousSpan,
    AnomalySignal,
    Cluster,
    ClusterStatus,
    ExperimentResult,
    FixArtifact,
    PromptProposal,
    RegressionTestCase,
    TraceSpan,
    Verification,
)
from nengok.errors import AgentRunnerLoadError

_HYPOTHESIS_JSON = json.dumps(
    {
        "summary": "s",
        "expected_behavior": "e",
        "actual_behavior": "a",
        "likely_cause": "c",
        "implicated_tools": [],
    }
)
_CASES_JSON = json.dumps(
    {
        "cases": [
            {"input": {"query": f"q{i}"}, "expected": {"a": "y"}, "metadata": {}}
            for i in range(MIN_REGRESSION_CASES + 1)
        ]
    }
)
_PROPOSAL_JSON = json.dumps({"proposed_prompt": "FIXED", "rationale": "r"})


class _RecordingSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        del key, value


class _NullTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_RecordingSpan]:
        del name, kwargs
        yield _RecordingSpan()


@pytest.fixture(autouse=True)
def _patched(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    Orchestrator._traced = False
    monkeypatch.setattr(orch_module, "get_tracer", lambda: _NullTracer())
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    yield
    Orchestrator._traced = False


def _span(span_id: str) -> TraceSpan:
    return TraceSpan(span_id=span_id, trace_id=f"t-{span_id}", name="agent")


class _PerProjectSampler:
    def __init__(self, spans_by_project: dict[str, list[TraceSpan]]) -> None:
        self.spans_by_project = spans_by_project
        self.calls: list[str | None] = []

    def sample(
        self,
        *,
        project_identifier: str | None = None,
        window_minutes: int | None = None,
    ) -> list[TraceSpan]:
        del window_minutes
        self.calls.append(project_identifier)
        return self.spans_by_project.get(project_identifier or "", [])


class _PassThroughFilter:
    def filter(self, spans: list[TraceSpan]) -> list[AnomalousSpan]:
        return [AnomalousSpan(span=s, signals=[AnomalySignal.ERROR_STATUS]) for s in spans]


class _PerBatchClusterer:
    """Build one cluster per call from whatever anomalies arrive."""

    def __init__(self) -> None:
        self.cost_tracker: Any = None

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        if not anomalies:
            return []
        now = datetime.now(UTC)
        span_ids = [a.span.span_id for a in anomalies]
        return [
            Cluster(
                cluster_id=f"c-{span_ids[0]}",
                name=f"cluster-{span_ids[0].split('-')[0]}",
                description="d",
                status=ClusterStatus.OPEN,
                member_span_ids=span_ids,
                exemplar_span_ids=span_ids[:5],
                hypothesis=None,
                created_at=now,
                updated_at=now,
                signals=[AnomalySignal.ERROR_STATUS.value],
            )
        ]


class _ExperimentRunner:
    def run(
        self,
        *,
        cluster: Cluster,
        cases: list[RegressionTestCase],
        proposal: PromptProposal,
    ) -> ExperimentResult:
        del cases, proposal
        return ExperimentResult(
            experiment_name=f"{cluster.cluster_id}-fix",
            experiment_id="exp",
            dataset_name="d",
            baseline_pass_rate=0.5,
            fix_pass_rate=1.0,
            golden_baseline_pass_rate=1.0,
            golden_fix_pass_rate=1.0,
        )


class _ArtifactWriter:
    def write(
        self,
        *,
        cluster: Cluster,
        cases: list[RegressionTestCase],
        proposal: PromptProposal,
        verification: Verification,
    ) -> FixArtifact:
        del cases, proposal
        return FixArtifact(
            cluster_id=cluster.cluster_id,
            prompt_path="/p",
            dataset_path="/d",
            rca_path="/r",
            verification=verification,
        )


class _StaticBaselineLoader:
    def load(self, project_name: str) -> str | None:
        return f"baseline for {project_name}"


class _NullLinker:
    def __init__(self) -> None:
        self.calls: list[list[Cluster]] = []
        self.cost_tracker: Any = None

    def link(self, clusters: list[Cluster]) -> list[Any]:
        self.calls.append(clusters)
        return []


def _config(tmp_path: Path, **overrides: Any) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        triage_enabled=False,
        min_cluster_size=1,
        **overrides,
    )


def test_cycle_covers_every_configured_project(tmp_path: Path) -> None:
    config = _config(tmp_path, project_identifiers=["proj-a", "proj-b"])
    orch = Orchestrator(config=config)

    sampler = _PerProjectSampler(
        {
            "proj-a": [_span("a-1"), _span("a-2")],
            "proj-b": [_span("b-1")],
        }
    )
    linker = _NullLinker()
    orch._sampler = sampler
    orch._anomaly_filter = _PassThroughFilter()
    orch._clusterer = _PerBatchClusterer()
    orch._linker = linker
    orch._hypothesizer = Hypothesizer(config=config, gemini_call=lambda _: _HYPOTHESIS_JSON)
    orch._test_generator = TestGenerator(config=config, gemini_call=lambda _: _CASES_JSON)
    orch._prompt_proposer = PromptProposer(
        config=config,
        gemini_call=lambda _: _PROPOSAL_JSON,
        baseline_loader=_StaticBaselineLoader(),
    )
    orch._experiment_runner = _ExperimentRunner()
    orch._artifact_writer = _ArtifactWriter()

    result = orch.run_once()

    assert sampler.calls == ["proj-a", "proj-b"]
    assert result.clusters_detected == 2
    assert len(linker.calls) == 1

    conn = sqlite3.connect(tmp_path / "state.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["cluster_id"]: dict(r) for r in conn.execute("SELECT * FROM nengok_clusters")}
        cycle = dict(conn.execute("SELECT * FROM nengok_cycles").fetchone())
    finally:
        conn.close()

    assert rows["c-a-1"]["project"] == "proj-a"
    assert rows["c-b-1"]["project"] == "proj-b"
    assert json.loads(cycle["projects_json"]) == ["proj-a", "proj-b"]


def test_quiet_project_skips_diagnosis(tmp_path: Path) -> None:
    config = _config(tmp_path, project_identifiers=["proj-a", "proj-b"])
    orch = Orchestrator(config=config)

    sampler = _PerProjectSampler({"proj-a": [_span("a-1")]})
    hypothesizer_calls: list[str] = []

    def fake_hypothesizer(prompt: str) -> str:
        hypothesizer_calls.append(prompt)
        return _HYPOTHESIS_JSON

    orch._sampler = sampler
    orch._anomaly_filter = _PassThroughFilter()
    orch._clusterer = _PerBatchClusterer()
    orch._linker = _NullLinker()
    orch._hypothesizer = Hypothesizer(config=config, gemini_call=fake_hypothesizer)
    orch._test_generator = TestGenerator(config=config, gemini_call=lambda _: _CASES_JSON)
    orch._prompt_proposer = PromptProposer(
        config=config,
        gemini_call=lambda _: _PROPOSAL_JSON,
        baseline_loader=_StaticBaselineLoader(),
    )
    orch._experiment_runner = _ExperimentRunner()
    orch._artifact_writer = _ArtifactWriter()

    result = orch.run_once()

    assert sampler.calls == ["proj-a", "proj-b"]
    assert result.clusters_detected == 1
    assert len(hypothesizer_calls) == 1


def test_bad_per_project_runner_spec_fails_at_init(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        project_identifiers=["proj-a"],
        agent_runners={"proj-a": "nonexistent_module.runner:Missing"},
    )
    with pytest.raises(AgentRunnerLoadError):
        Orchestrator(config=config)


def test_mapped_runner_wins_and_fallback_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registered: dict[str, Any] = {}

    class _FakeRunner:
        def __init__(self, label: str) -> None:
            self.label = label

        @property
        def name(self) -> str:
            return self.label

        def run(self, agent_input: dict[str, Any], prompt: str) -> dict[str, Any]:
            del prompt
            return agent_input

    def fake_load_runner(spec: str, kwargs: Any) -> Any:
        del kwargs
        return _FakeRunner(spec)

    def fake_register(project: str, runner: Any) -> None:
        registered[project] = runner

    monkeypatch.setattr(orch_module, "load_runner", fake_load_runner)
    monkeypatch.setattr(orch_module, "register_runner", fake_register)

    config = _config(
        tmp_path,
        project_identifiers=["proj-a", "proj-b"],
        agent_runner="shared.module:SharedRunner",
        agent_runners={"proj-b": "special.module:SpecialRunner"},
    )
    Orchestrator(config=config)

    assert registered["proj-a"].label == "shared.module:SharedRunner"
    assert registered["proj-b"].label == "special.module:SpecialRunner"
