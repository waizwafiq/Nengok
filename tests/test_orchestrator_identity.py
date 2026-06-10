"""
Cross-cycle cluster identity through the orchestrator.

Two simulated cycles run against a real `StateStore` so the matcher,
the member union, the span-to-cluster backfill, and the status policy
are exercised end to end. Gemini stays faked throughout.
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
from nengok.state.store import StateStore

_HYPOTHESIS_JSON = json.dumps(
    {
        "summary": "schema drift",
        "expected_behavior": "ISO-8601 string",
        "actual_behavior": "UNIX epoch int",
        "likely_cause": "flights v3 contract change",
        "implicated_tools": ["tool.flights.search"],
    }
)

_CASES_JSON = json.dumps(
    {
        "cases": [
            {"input": {"query": f"plan trip {i}"}, "expected": {"a": "y"}, "metadata": {}}
            for i in range(MIN_REGRESSION_CASES + 1)
        ]
    }
)

_PROPOSAL_JSON = json.dumps({"proposed_prompt": "FIXED PROMPT", "rationale": "addresses drift"})


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


class _Clusterer:
    def __init__(self, clusters: list[Cluster]) -> None:
        self._clusters = clusters
        self.cost_tracker: Any = None

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        del anomalies
        return self._clusters


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
            experiment_id="exp-ok",
            dataset_name="d",
            baseline_pass_rate=0.5,
            fix_pass_rate=1.0,
            golden_baseline_pass_rate=1.0,
            golden_fix_pass_rate=1.0,
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


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def dispatch(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _reset_traced_flag(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    Orchestrator._traced = False
    monkeypatch.setattr(orch_module, "get_tracer", lambda: _NullTracer())
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    yield
    Orchestrator._traced = False


def _span(span_id: str) -> TraceSpan:
    return TraceSpan(
        span_id=span_id,
        trace_id=f"t-{span_id}",
        name="agent",
        started_at=datetime.now(UTC),
    )


def _anomaly(span_id: str) -> AnomalousSpan:
    return AnomalousSpan(span=_span(span_id), signals=[AnomalySignal.ERROR_STATUS])


def _cluster(cluster_id: str, name: str, span_ids: list[str]) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        description="flights departure_time drifted to epoch ints",
        status=ClusterStatus.OPEN,
        member_span_ids=span_ids,
        exemplar_span_ids=span_ids[:5],
        hypothesis=None,
        created_at=now,
        updated_at=now,
        signals=[AnomalySignal.ERROR_STATUS.value],
    )


def _run_cycle(
    tmp_path: Path,
    *,
    span_ids: list[str],
    cluster: Cluster,
    min_cluster_size: int = 1,
    hypothesizer_calls: list[str] | None = None,
) -> tuple[Orchestrator, _ArtifactWriter, _RecordingDispatcher]:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        project_identifier="travel-planner-agent",
        triage_enabled=False,
        min_cluster_size=min_cluster_size,
    )
    orch = Orchestrator(config=config)
    writer = _ArtifactWriter()
    dispatcher = _RecordingDispatcher()

    def fake_hypothesizer(prompt: str) -> str:
        if hypothesizer_calls is not None:
            hypothesizer_calls.append(prompt)
        return _HYPOTHESIS_JSON

    orch._sampler = _Sampler([_span(sid) for sid in span_ids])
    orch._anomaly_filter = _AnomalyFilter([_anomaly(sid) for sid in span_ids])
    orch._clusterer = _Clusterer([cluster])
    orch._hypothesizer = Hypothesizer(config=config, gemini_call=fake_hypothesizer)
    orch._test_generator = TestGenerator(config=config, gemini_call=lambda _: _CASES_JSON)
    orch._prompt_proposer = PromptProposer(config=config, gemini_call=lambda _: _PROPOSAL_JSON)
    orch._experiment_runner = _ExperimentRunner()
    orch._artifact_writer = writer
    orch._notifier_dispatcher = dispatcher

    result = orch.run_once()
    del result
    return orch, writer, dispatcher


def _rows(tmp_path: Path) -> list[dict]:
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM nengok_clusters").fetchall()]
    finally:
        conn.close()


def _seen_span_clusters(tmp_path: Path) -> dict[str, str | None]:
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT span_id, cluster_id FROM nengok_seen_spans").fetchall()
        return {r["span_id"]: r["cluster_id"] for r in rows}
    finally:
        conn.close()


def test_recurring_failure_mode_keeps_one_cluster_row(tmp_path: Path) -> None:
    _run_cycle(
        tmp_path,
        span_ids=["s1", "s2"],
        cluster=_cluster("c-cycle1", "flights-schema-drift", ["s1", "s2"]),
    )
    _run_cycle(
        tmp_path,
        span_ids=["s3", "s4"],
        cluster=_cluster("c-cycle2", "flights-schema-drift", ["s3", "s4"]),
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["cluster_id"] == "c-cycle1"
    members = json.loads(rows[0]["member_spans_json"])
    assert set(members) == {"s1", "s2", "s3", "s4"}

    assigned = _seen_span_clusters(tmp_path)
    assert all(assigned[sid] == "c-cycle1" for sid in ("s1", "s2", "s3", "s4"))


def test_rejected_cluster_reaccretes_silently(tmp_path: Path) -> None:
    _run_cycle(
        tmp_path,
        span_ids=["s1"],
        cluster=_cluster("c-first", "weather-unit-mismatch", ["s1"]),
    )
    store = StateStore(tmp_path / "state.db")
    store.mark_status("c-first", ClusterStatus.REJECTED)

    calls: list[str] = []
    _, writer, dispatcher = _run_cycle(
        tmp_path,
        span_ids=["s2"],
        cluster=_cluster("c-second", "weather-unit-mismatch", ["s2"]),
        hypothesizer_calls=calls,
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == ClusterStatus.REJECTED.value
    assert set(json.loads(rows[0]["member_spans_json"])) == {"s1", "s2"}
    assert calls == []
    assert writer.writes == []
    assert dispatcher.events == []


def test_approved_cluster_rematch_escalates_with_fix_regressed(tmp_path: Path) -> None:
    _run_cycle(
        tmp_path,
        span_ids=["s1"],
        cluster=_cluster("c-first", "hotels-timeout", ["s1"]),
    )
    store = StateStore(tmp_path / "state.db")
    store.mark_status("c-first", ClusterStatus.APPROVED)

    _, writer, dispatcher = _run_cycle(
        tmp_path,
        span_ids=["s2"],
        cluster=_cluster("c-second", "hotels-timeout", ["s2"]),
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == ClusterStatus.ESCALATED.value
    assert writer.writes == []
    assert len(dispatcher.events) == 1
    assert dispatcher.events[0].event_kind == "escalation"
    assert dispatcher.events[0].reason == "fix_regressed"


def test_min_cluster_size_holdback_releases_after_accretion(tmp_path: Path) -> None:
    calls_first: list[str] = []
    _, writer_first, _ = _run_cycle(
        tmp_path,
        span_ids=["s1", "s2"],
        cluster=_cluster("c-small", "flights-schema-drift", ["s1", "s2"]),
        min_cluster_size=3,
        hypothesizer_calls=calls_first,
    )

    rows = _rows(tmp_path)
    assert rows[0]["status"] == ClusterStatus.OPEN.value
    assert calls_first == []
    assert writer_first.writes == []

    calls_second: list[str] = []
    _, writer_second, _ = _run_cycle(
        tmp_path,
        span_ids=["s3"],
        cluster=_cluster("c-more", "flights-schema-drift", ["s3"]),
        min_cluster_size=3,
        hypothesizer_calls=calls_second,
    )

    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["cluster_id"] == "c-small"
    assert set(json.loads(rows[0]["member_spans_json"])) == {"s1", "s2", "s3"}
    assert rows[0]["status"] == ClusterStatus.FIX_PROPOSED.value
    assert len(calls_second) == 1
    assert len(writer_second.writes) == 1
