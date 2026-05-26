"""Cycle budget abort writes an incident and skips remaining clusters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core.cost import CostTracker
from nengok.core.orchestrator import Orchestrator
from nengok.core.types import (
    AnomalousSpan,
    AnomalySignal,
    Cluster,
    ClusterStatus,
    ExperimentResult,
    PromptProposal,
    RegressionTestCase,
    RootCauseHypothesis,
    TraceSpan,
)


class _RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


class _NullTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_RecordingSpan]:
        del kwargs
        yield _RecordingSpan(name)


def _trace_span(span_id: str) -> TraceSpan:
    return TraceSpan(span_id=span_id, trace_id=f"t-{span_id}", name="agent")


def _anomaly(span_id: str) -> AnomalousSpan:
    return AnomalousSpan(span=_trace_span(span_id), signals=[AnomalySignal.HIGH_LATENCY])


def _cluster(cluster_id: str) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=cluster_id,
        description="d",
        status=ClusterStatus.OPEN,
        member_span_ids=[f"s-{cluster_id}"],
        exemplar_span_ids=[f"s-{cluster_id}"],
        hypothesis=RootCauseHypothesis(
            summary="s",
            expected_behavior="e",
            actual_behavior="a",
            likely_cause="c",
        ),
        created_at=now,
        updated_at=now,
    )


class _Sampler:
    def __init__(self, spans: list[TraceSpan]) -> None:
        self._spans = spans

    def sample(self) -> list[TraceSpan]:
        return self._spans


class _AnomalyFilter:
    def __init__(self, anomalies: list[AnomalousSpan]) -> None:
        self._anomalies = anomalies

    def filter(self, spans: list[TraceSpan]) -> list[AnomalousSpan]:
        del spans
        return self._anomalies


class _State:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, ClusterStatus]] = []
        self.experiments: list[str] = []

    def deduplicate(self, anomalies: list[AnomalousSpan]) -> list[AnomalousSpan]:
        return anomalies

    def upsert_cluster(self, cluster: Cluster, *, first_seen: datetime | None = None) -> None:
        del cluster, first_seen

    def mark_status(self, cluster_id: str, status: ClusterStatus) -> None:
        self.statuses.append((cluster_id, status))

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        del result
        self.experiments.append(cluster_id)

    def record_cycle_usage(self, **_: object) -> None:
        return


class _Clusterer:
    def __init__(self, clusters: list[Cluster]) -> None:
        self._clusters = clusters
        self.cost_tracker: CostTracker | None = None

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        del anomalies
        return self._clusters


class _Hypothesizer:
    def __init__(self) -> None:
        self.cost_tracker: CostTracker | None = None

    def hypothesize(self, cluster: Cluster, *, current_prompt: str | None = None) -> RootCauseHypothesis:
        del current_prompt
        assert cluster.hypothesis is not None
        return cluster.hypothesis


class _SpendingTestGen:
    """Burns through the cost tracker each generate() call."""

    def __init__(self, tokens_per_cluster: int) -> None:
        self._tokens_per_cluster = tokens_per_cluster
        self.cost_tracker: CostTracker | None = None
        self.calls: list[str] = []

    def generate(self, cluster: Cluster) -> list[RegressionTestCase]:
        self.calls.append(cluster.cluster_id)
        if self.cost_tracker is not None:
            self.cost_tracker.record(
                prompt_tokens=self._tokens_per_cluster,
                completion_tokens=0,
            )
        return [
            RegressionTestCase(
                case_id=f"{cluster.cluster_id}-1",
                input={"q": "x"},
                expected={"a": "y"},
            )
        ]


class _PromptProposer:
    def __init__(self) -> None:
        self.cost_tracker: CostTracker | None = None

    def load_baseline_prompt(self) -> str:
        return "BASE"

    def propose(self, cluster: Cluster, *, baseline_prompt: str) -> PromptProposal:
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline_prompt,
            proposed_prompt="FIX",
            rationale="r",
        )


class _ExperimentRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, *, cluster: Cluster, cases: Any, proposal: Any) -> ExperimentResult:
        del cases, proposal
        self.calls.append(cluster.cluster_id)
        return ExperimentResult(
            experiment_name=f"{cluster.cluster_id}-fix",
            experiment_id="ok",
            dataset_name="d",
            baseline_pass_rate=0.5,
            fix_pass_rate=1.0,
            golden_baseline_pass_rate=1.0,
            golden_fix_pass_rate=1.0,
        )


@pytest.fixture(autouse=True)
def _reset_traced_flag() -> Iterator[None]:
    Orchestrator._traced = False
    yield
    Orchestrator._traced = False


@pytest.fixture
def patched_tracer(monkeypatch: pytest.MonkeyPatch) -> _NullTracer:
    from nengok.core import orchestrator as orch_module

    tracer = _NullTracer()
    monkeypatch.setattr(orch_module, "get_tracer", lambda: tracer)
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    return tracer


def test_cycle_aborts_when_budget_exceeded(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer

    base_config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    config = replace(base_config, gemini_cycle_token_budget=10_000)
    orch = Orchestrator(config=config)

    clusters = [_cluster("c1"), _cluster("c2"), _cluster("c3")]
    anomalies = [_anomaly(c.cluster_id) for c in clusters]
    state = _State()
    runner = _ExperimentRunner()
    test_gen = _SpendingTestGen(tokens_per_cluster=8_000)

    orch._sampler = _Sampler([_trace_span(c.cluster_id) for c in clusters])
    orch._anomaly_filter = _AnomalyFilter(anomalies)
    orch._state = state
    orch._clusterer = _Clusterer(clusters)
    orch._hypothesizer = _Hypothesizer()
    orch._test_generator = test_gen
    orch._prompt_proposer = _PromptProposer()
    orch._experiment_runner = runner

    result = orch.run_once()

    assert test_gen.calls == ["c1", "c2"]
    assert runner.calls == ["c1", "c2"]
    assert result.fixes_proposed == 2
    incident_files = list((config.artifacts_dir / "incidents").rglob("over-budget.md"))
    assert incident_files, "expected an over-budget incident artifact"
    rendered = incident_files[0].read_text(encoding="utf-8")
    assert "c3" in rendered
    assert "token_budget" in rendered
