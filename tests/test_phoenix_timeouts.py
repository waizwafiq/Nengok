"""Phoenix client timeouts escalate, not abort, the cycle."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.core.orchestrator import Orchestrator
from nengok.core.types import (
    AnomalousSpan,
    AnomalySignal,
    Cluster,
    ClusterStatus,
    PromptProposal,
    RegressionTestCase,
    RootCauseHypothesis,
    TraceSpan,
)
from nengok.errors import PhoenixTimeoutError
from nengok.phoenix.client import PhoenixWrapper


class _SlowSpans:
    def __init__(self, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds

    def get_spans(self, **_: Any) -> list[Any]:
        time.sleep(self._delay_seconds)
        return []


class _SlowClient:
    def __init__(self, delay_seconds: float) -> None:
        self.spans = _SlowSpans(delay_seconds)


def test_slow_read_raises_phoenix_timeout(tmp_config: NengokConfig) -> None:
    config = replace(tmp_config, phoenix_read_timeout_seconds=0.05)
    wrapper = PhoenixWrapper(config)
    wrapper._client = _SlowClient(delay_seconds=0.5)

    with pytest.raises(PhoenixTimeoutError) as excinfo:
        wrapper.get_spans(project_identifier="any", limit=10)

    err = excinfo.value
    assert err.method == "spans.get_spans"
    assert err.timeout_seconds == 0.05
    assert err.observed_seconds is not None
    assert err.observed_seconds > 0.0


class _RecordingSpan:
    def __init__(self, name: str) -> None:
        self.name = name

    def set_attribute(self, key: str, value: Any) -> None:
        del key, value


class _NullTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_RecordingSpan]:
        del kwargs
        yield _RecordingSpan(name)


def _make_trace_span(span_id: str) -> TraceSpan:
    return TraceSpan(span_id=span_id, trace_id=f"t-{span_id}", name="agent")


def _make_anomaly(span_id: str) -> AnomalousSpan:
    return AnomalousSpan(span=_make_trace_span(span_id), signals=[AnomalySignal.HIGH_LATENCY])


def _make_cluster(cluster_id: str) -> Cluster:
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
        self.statuses: list[tuple[str, ClusterStatus]] = []

    def deduplicate(self, anomalies: list[AnomalousSpan]) -> list[AnomalousSpan]:
        return anomalies

    def list_clusters(self, **kwargs: object) -> list[dict]:
        del kwargs
        return []

    def assign_spans_to_cluster(self, span_ids: list[str], cluster_id: str) -> None:
        del span_ids, cluster_id

    def upsert_cluster(self, cluster: Cluster, *, first_seen: datetime | None = None) -> None:
        del cluster, first_seen

    def mark_status(self, cluster_id: str, status: ClusterStatus) -> None:
        self.statuses.append((cluster_id, status))

    def record_experiment(self, **_: Any) -> None:
        return

    def record_cycle(self, _record: Any) -> None:
        return


class _Clusterer:
    def __init__(self, clusters: list[Cluster]) -> None:
        self._clusters = clusters

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        del anomalies
        return self._clusters


class _Hypothesizer:
    def hypothesize(self, cluster: Cluster, *, current_prompt: str | None = None) -> RootCauseHypothesis:
        del current_prompt
        assert cluster.hypothesis is not None
        return cluster.hypothesis


class _TestGenerator:
    def generate(self, cluster: Cluster) -> list[RegressionTestCase]:
        return [
            RegressionTestCase(
                case_id=f"{cluster.cluster_id}-1",
                input={"q": "x"},
                expected={"a": "y"},
            )
        ]


class _PromptProposer:
    def load_baseline_prompt(self, project: str | None = None) -> str:
        del project
        return "BASE"

    def propose(self, cluster: Cluster, *, baseline_prompt: str) -> PromptProposal:
        return PromptProposal(
            cluster_id=cluster.cluster_id,
            baseline_prompt=baseline_prompt,
            proposed_prompt="FIX",
            rationale="r",
        )


class _BoomRunner:
    def __init__(self, raise_on: set[str]) -> None:
        self._raise_on = raise_on
        self.calls: list[str] = []

    def run(self, *, cluster: Cluster, cases: Any, proposal: Any) -> Any:
        del cases, proposal
        self.calls.append(cluster.cluster_id)
        if cluster.cluster_id in self._raise_on:
            raise PhoenixTimeoutError(
                f"boom for {cluster.cluster_id}",
                method="experiments.run_experiment",
                timeout_seconds=0.05,
                observed_seconds=0.1,
            )
        from nengok.core.types import ExperimentResult

        return ExperimentResult(
            experiment_name=f"{cluster.cluster_id}-fix",
            experiment_id="ok",
            dataset_name="d",
            baseline_pass_rate=0.5,
            fix_pass_rate=1.0,
            golden_baseline_pass_rate=1.0,
            golden_fix_pass_rate=1.0,
        )


def _build_orchestrator(
    tmp_path: Path, *, raise_on: set[str], clusters: list[Cluster]
) -> tuple[Orchestrator, _State, _BoomRunner]:
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
    anomalies = [_make_anomaly(c.cluster_id) for c in clusters]
    state = _State()
    runner = _BoomRunner(raise_on=raise_on)
    orch._sampler = _Sampler([_make_trace_span(c.cluster_id) for c in clusters])
    orch._anomaly_filter = _AnomalyFilter(anomalies)
    orch._state = state
    orch._clusterer = _Clusterer(clusters)
    orch._hypothesizer = _Hypothesizer()
    orch._test_generator = _TestGenerator()
    orch._prompt_proposer = _PromptProposer()
    orch._experiment_runner = runner
    return orch, state, runner


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


def test_orchestrator_escalates_on_phoenix_timeout(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer
    cluster_a = _make_cluster("c-a")
    cluster_b = _make_cluster("c-b")
    orch, state, runner = _build_orchestrator(
        tmp_path,
        raise_on={"c-a"},
        clusters=[cluster_a, cluster_b],
    )

    result = orch.run_once()

    assert (cluster_a.cluster_id, ClusterStatus.ESCALATED) in state.statuses
    assert (cluster_b.cluster_id, ClusterStatus.FIX_PROPOSED) in state.statuses
    assert runner.calls == ["c-a", "c-b"]
    assert result.escalations == 1
    assert result.fixes_proposed == 1

    incidents_root = orch.config.artifacts_dir / "incidents"
    timeout_files = list(incidents_root.rglob("phoenix-timeout-c-a.md"))
    assert timeout_files, "expected an incident artifact for the timed-out cluster"
    rendered = timeout_files[0].read_text(encoding="utf-8")
    assert "experiments.run_experiment" in rendered
    assert "c-a" in rendered
