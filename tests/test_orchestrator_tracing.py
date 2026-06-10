"""Tests for Nengok's self-instrumentation wiring in the orchestrator."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core import orchestrator as orch_module
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
    RootCauseHypothesis,
    TraceSpan,
    Verification,
    VerificationOutcome,
)


class _RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_RecordingSpan]:
        del kwargs
        span = _RecordingSpan(name)
        self.spans.append(span)
        yield span

    def names(self) -> list[str]:
        return [s.name for s in self.spans]

    def by_name(self, name: str) -> list[_RecordingSpan]:
        return [s for s in self.spans if s.name == name]


def _make_trace_span(span_id: str) -> TraceSpan:
    return TraceSpan(span_id=span_id, trace_id=f"t-{span_id}", name="agent")


def _make_anomaly(span_id: str, signals: list[AnomalySignal]) -> AnomalousSpan:
    return AnomalousSpan(span=_make_trace_span(span_id), signals=signals)


def _make_cluster(cluster_id: str, name: str, member_ids: list[str]) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        description="d",
        status=ClusterStatus.OPEN,
        member_span_ids=member_ids,
        exemplar_span_ids=member_ids[:2],
        hypothesis=None,
        created_at=now,
        updated_at=now,
    )


_HYPOTHESIS = RootCauseHypothesis(
    summary="s",
    expected_behavior="e",
    actual_behavior="a",
    likely_cause="c",
    implicated_tools=["t"],
)


class _Sampler:
    def __init__(self, spans: list[TraceSpan]) -> None:
        self._spans = spans

    def sample(self, **kwargs: object) -> list[TraceSpan]:
        del kwargs
        return self._spans


class _AnomalyFilter:
    def __init__(self, anomalies: list[AnomalousSpan]) -> None:
        self._anomalies = anomalies

    def filter(self, spans: list[TraceSpan]) -> list[AnomalousSpan]:
        del spans
        return self._anomalies


class _State:
    def __init__(self) -> None:
        self.upserts: list[tuple[Cluster, datetime | None]] = []
        self.statuses: list[tuple[str, ClusterStatus]] = []
        self.experiments: list[tuple[str, ExperimentResult]] = []

    def deduplicate(self, anomalies: list[AnomalousSpan]) -> list[AnomalousSpan]:
        return anomalies

    def list_clusters(self, **kwargs: object) -> list[dict]:
        del kwargs
        return []

    def assign_spans_to_cluster(self, span_ids: list[str], cluster_id: str) -> None:
        del span_ids, cluster_id

    def list_cluster_links(self, cluster_id: str) -> list[dict]:
        del cluster_id
        return []

    def list_recent_active_clusters(self, *, since: object) -> list[dict]:
        del since
        return []

    def insert_cluster_link(self, **kwargs: object) -> str | None:
        del kwargs
        return None

    def list_cluster_feedback(self, project: str | None, limit: int = 5) -> list[dict]:
        del project, limit
        return []

    def upsert_cluster(self, cluster: Cluster, *, first_seen: datetime | None = None) -> None:
        self.upserts.append((cluster, first_seen))

    def mark_status(self, cluster_id: str, status: ClusterStatus) -> None:
        self.statuses.append((cluster_id, status))

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        self.experiments.append((cluster_id, result))

    def record_cycle(self, _record: object) -> None:
        return


class _Clusterer:
    def __init__(self, clusters: list[Cluster]) -> None:
        self._clusters = clusters

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        del anomalies
        return self._clusters


class _Hypothesizer:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def hypothesize(
        self,
        cluster: Cluster,
        *,
        current_prompt: str | None = None,
        linked_summaries: list[str] | None = None,
    ) -> RootCauseHypothesis:
        del linked_summaries
        del cluster
        self.calls.append(current_prompt)
        return _HYPOTHESIS


class _TestGenerator:
    def generate(self, cluster: Cluster) -> list[RegressionTestCase]:
        return [
            RegressionTestCase(
                case_id=f"{cluster.cluster_id}-c1",
                input={"q": "x"},
                expected={"a": "y"},
            )
        ]


class _PromptProposer:
    def __init__(self, baseline: str = "BASE") -> None:
        self._baseline = baseline
        self.injected_baselines: list[str | None] = []

    def load_baseline_prompt(self, project: str | None = None) -> str:
        del project
        return self._baseline

    def propose(self, cluster: Cluster, *, baseline_prompt: str | None = None) -> PromptProposal:
        self.injected_baselines.append(baseline_prompt)
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline_prompt or self._baseline,
            proposed_prompt="FIX",
            rationale="r",
        )


class _ExperimentRunner:
    def __init__(
        self,
        *,
        fix_pass_rate: float = 1.0,
        golden_baseline: float = 1.0,
        golden_fix: float = 1.0,
    ) -> None:
        self._fix_pass_rate = fix_pass_rate
        self._golden_baseline = golden_baseline
        self._golden_fix = golden_fix

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
            experiment_id="exp-1",
            dataset_name=f"{cluster.name}-regression",
            baseline_pass_rate=0.5,
            fix_pass_rate=self._fix_pass_rate,
            golden_baseline_pass_rate=self._golden_baseline,
            golden_fix_pass_rate=self._golden_fix,
            per_case=[],
        )


class _ArtifactWriter:
    def __init__(self) -> None:
        self.writes: list[FixArtifact] = []

    def write(
        self,
        *,
        cluster: Cluster,
        cases: list[RegressionTestCase],
        proposal: PromptProposal,
        verification: Verification,
    ) -> FixArtifact:
        del cases, proposal
        artifact = FixArtifact(
            cluster_id=cluster.cluster_id,
            prompt_path="/p",
            dataset_path="/d",
            rca_path="/r",
            verification=verification,
        )
        self.writes.append(artifact)
        return artifact


@pytest.fixture(autouse=True)
def _reset_traced_flag() -> Iterator[None]:
    Orchestrator._traced = False
    yield
    Orchestrator._traced = False


@pytest.fixture
def patched_tracer(monkeypatch: pytest.MonkeyPatch) -> _RecordingTracer:
    tracer = _RecordingTracer()
    monkeypatch.setattr(orch_module, "get_tracer", lambda: tracer)
    return tracer


@pytest.fixture
def register_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def fake_register() -> None:
        calls.append(1)

    monkeypatch.setattr(orch_module, "register_meta_tracer", fake_register)
    return calls


def _build_orchestrator(
    tmp_path: Path,
    *,
    anomalies: list[AnomalousSpan],
    clusters: list[Cluster],
    fix_pass_rate: float = 1.0,
    golden_baseline: float = 1.0,
    golden_fix: float = 1.0,
) -> tuple[Orchestrator, _State, _ArtifactWriter]:
    config = NengokConfig.load(
        min_cluster_size=1,
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        triage_enabled=False,
    )
    orch = Orchestrator(config=config)
    state = _State()
    writer = _ArtifactWriter()
    orch._sampler = _Sampler([_make_trace_span(a.span.span_id) for a in anomalies])
    orch._anomaly_filter = _AnomalyFilter(anomalies)
    orch._state = state
    orch._clusterer = _Clusterer(clusters)
    orch._hypothesizer = _Hypothesizer()
    orch._test_generator = _TestGenerator()
    orch._prompt_proposer = _PromptProposer()
    orch._experiment_runner = _ExperimentRunner(
        fix_pass_rate=fix_pass_rate,
        golden_baseline=golden_baseline,
        golden_fix=golden_fix,
    )
    orch._artifact_writer = writer
    return orch, state, writer


def test_no_anomalies_emits_only_cycle_and_observer_spans(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del register_calls
    orch, _, _ = _build_orchestrator(tmp_path, anomalies=[], clusters=[])

    result = orch.run_once()

    assert result.clusters_detected == 0
    assert patched_tracer.names() == ["nengok.cycle", "observer"]
    observer = patched_tracer.by_name("observer")[0]
    assert observer.attributes["nengok.observer.span_count"] == 0
    assert observer.attributes["nengok.observer.anomaly_count"] == 0
    assert observer.attributes["nengok.observer.new_anomaly_count"] == 0


def test_full_pass_emits_each_stage_with_cluster_attributes(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del register_calls
    anomalies = [
        _make_anomaly("s1", [AnomalySignal.HIGH_LATENCY, AnomalySignal.ERROR_STATUS]),
        _make_anomaly("s2", [AnomalySignal.HIGH_LATENCY]),
        _make_anomaly("s3", [AnomalySignal.TOOL_FAILURE]),
    ]
    cluster = _make_cluster("cid-1", "schema-drift", ["s1", "s2", "s3"])
    orch, state, writer = _build_orchestrator(tmp_path, anomalies=anomalies, clusters=[cluster])

    result = orch.run_once()

    assert patched_tracer.names() == [
        "nengok.cycle",
        "observer",
        "diagnoser",
        "linker",
        "fixer",
        "verifier",
    ]

    diagnoser = patched_tracer.by_name("diagnoser")[0]
    assert diagnoser.attributes["nengok.diagnoser.cluster_count"] == 1

    fixer = patched_tracer.by_name("fixer")[0]
    assert fixer.attributes["nengok.cluster.id"] == "cid-1"
    assert fixer.attributes["nengok.cluster.name"] == "schema-drift"
    assert fixer.attributes["nengok.cluster.member_count"] == 3
    assert fixer.attributes["nengok.cluster.signal.high_latency"] == 2
    assert fixer.attributes["nengok.cluster.signal.error_status"] == 1
    assert fixer.attributes["nengok.cluster.signal.tool_failure"] == 1
    assert fixer.attributes["nengok.fixer.case_count"] == 1

    verifier = patched_tracer.by_name("verifier")[0]
    assert verifier.attributes["nengok.cluster.id"] == "cid-1"
    assert verifier.attributes["nengok.verifier.outcome"] == "passed"

    cycle = patched_tracer.by_name("nengok.cycle")[0]
    assert cycle.attributes["nengok.cycle.clusters_detected"] == 1
    assert cycle.attributes["nengok.cycle.fixes_proposed"] == 1
    assert cycle.attributes["nengok.cycle.escalations"] == 0

    assert result.fixes_proposed == 1
    assert len(writer.writes) == 1
    assert (cluster.cluster_id, ClusterStatus.FIX_PROPOSED) in state.statuses
    assert len(state.experiments) == 1
    persisted_cluster_id, persisted_result = state.experiments[0]
    assert persisted_cluster_id == cluster.cluster_id
    assert persisted_result.experiment_id == "exp-1"


def test_verifier_records_failure_outcome_and_escalation(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del register_calls
    anomalies = [_make_anomaly("s1", [AnomalySignal.HIGH_LATENCY])]
    cluster = _make_cluster("cid-1", "drift", ["s1"])
    orch, state, _ = _build_orchestrator(
        tmp_path,
        anomalies=anomalies,
        clusters=[cluster],
        fix_pass_rate=0.3,
    )

    result = orch.run_once()

    assert result.escalations == 1
    verifier = patched_tracer.by_name("verifier")[0]
    assert verifier.attributes["nengok.verifier.outcome"] == VerificationOutcome.FAILED_REGRESSION.value
    assert (cluster.cluster_id, ClusterStatus.ESCALATED) in state.statuses


def test_dry_run_skips_verifier_span(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del register_calls
    anomalies = [_make_anomaly("s1", [AnomalySignal.HIGH_LATENCY])]
    cluster = _make_cluster("cid-1", "drift", ["s1"])
    orch, _, writer = _build_orchestrator(tmp_path, anomalies=anomalies, clusters=[cluster])

    orch.run_once(dry_run=True)

    assert "fixer" in patched_tracer.names()
    assert "verifier" not in patched_tracer.names()
    assert writer.writes == []
    cycle = patched_tracer.by_name("nengok.cycle")[0]
    assert cycle.attributes["nengok.dry_run"] is True


def test_baseline_prompt_threaded_to_hypothesizer_and_proposer(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del patched_tracer, register_calls
    anomalies = [_make_anomaly("s1", [AnomalySignal.HIGH_LATENCY])]
    cluster = _make_cluster("cid-1", "drift", ["s1"])
    orch, _, _ = _build_orchestrator(tmp_path, anomalies=anomalies, clusters=[cluster])

    hypothesizer = _Hypothesizer()
    proposer = _PromptProposer(baseline="BASELINE-PROMPT")
    orch._hypothesizer = hypothesizer
    orch._prompt_proposer = proposer

    orch.run_once()

    assert hypothesizer.calls == ["BASELINE-PROMPT"]
    assert proposer.injected_baselines == ["BASELINE-PROMPT"]


def test_register_meta_tracer_runs_once_across_runs(
    tmp_path: Path,
    patched_tracer: _RecordingTracer,
    register_calls: list[int],
) -> None:
    del patched_tracer
    orch, _, _ = _build_orchestrator(tmp_path, anomalies=[], clusters=[])

    orch.run_once()
    orch.run_once()

    assert register_calls == [1]
