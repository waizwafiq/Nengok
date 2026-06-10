"""Coverage for the cycles table extensions added in 9.4."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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
    CycleRecord,
    CycleStatus,
    ExperimentResult,
    TraceSpan,
)
from nengok.state.store import StateStore


def _record(
    cycle_id: str,
    *,
    started_at: datetime,
    status: CycleStatus = CycleStatus.OK,
    clusters_processed: int = 0,
    clusters_discovered: int = 0,
    gemini_tokens: int = 0,
    gemini_dollars: float = 0.0,
    error_message: str | None = None,
) -> CycleRecord:
    return CycleRecord(
        cycle_id=cycle_id,
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=30),
        status=status,
        clusters_processed=clusters_processed,
        clusters_discovered=clusters_discovered,
        gemini_tokens=gemini_tokens,
        gemini_dollars=gemini_dollars,
        error_message=error_message,
    )


def test_record_cycle_persists_status_and_cluster_counts(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    started = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)

    store.record_cycle(
        _record(
            "c-1",
            started_at=started,
            status=CycleStatus.OVER_BUDGET,
            clusters_processed=2,
            clusters_discovered=5,
            gemini_tokens=4_321,
            gemini_dollars=0.42,
        )
    )

    rows = store.list_recent_cycles(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "over_budget"
    assert row["clusters_processed"] == 2
    assert row["clusters_discovered"] == 5
    assert row["gemini_tokens"] == 4_321
    assert row["gemini_dollars"] == 0.42
    assert row["error_message"] is None


def test_record_cycle_upserts_on_same_id(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    started = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)

    store.record_cycle(
        _record(
            "c-1",
            started_at=started,
            status=CycleStatus.OK,
            clusters_processed=1,
            clusters_discovered=1,
            gemini_tokens=100,
        )
    )
    store.record_cycle(
        _record(
            "c-1",
            started_at=started,
            status=CycleStatus.FAILED,
            clusters_processed=2,
            clusters_discovered=3,
            gemini_tokens=500,
            error_message="boom",
        )
    )

    rows = store.list_recent_cycles(limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["gemini_tokens"] == 500
    assert rows[0]["error_message"] == "boom"


def test_list_recent_cycles_orders_newest_first_and_respects_limit(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    base = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    for index in range(12):
        store.record_cycle(
            _record(
                f"c-{index:02d}",
                started_at=base + timedelta(hours=index),
                status=CycleStatus.OK,
            )
        )

    rows = store.list_recent_cycles(limit=5)
    assert [row["cycle_id"] for row in rows] == ["c-11", "c-10", "c-09", "c-08", "c-07"]


def test_dashboard_overview_exposes_recent_cycles_and_status_counts(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)
    store.record_cycle(
        _record(
            "c-ok",
            started_at=now - timedelta(hours=2),
            status=CycleStatus.OK,
            clusters_processed=3,
            clusters_discovered=3,
            gemini_dollars=0.10,
        )
    )
    store.record_cycle(
        _record(
            "c-over",
            started_at=now - timedelta(hours=1),
            status=CycleStatus.OVER_BUDGET,
            clusters_processed=1,
            clusters_discovered=2,
            gemini_dollars=0.20,
        )
    )
    store.record_cycle(
        _record(
            "c-fail",
            started_at=now,
            status=CycleStatus.FAILED,
            clusters_processed=0,
            clusters_discovered=0,
            error_message="phoenix unreachable",
        )
    )

    overview = store.dashboard_overview()

    assert "recent_cycles" in overview
    recent = overview["recent_cycles"]
    assert [cycle["cycle_id"] for cycle in recent] == ["c-fail", "c-over", "c-ok"]
    assert recent[0]["error_message"] == "phoenix unreachable"

    counts = overview["recent_cycle_status_counts"]
    assert counts == {"ok": 1, "over_budget": 1, "failed": 1}


class _RecordingSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        del key, value


class _NullTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Iterator[_RecordingSpan]:
        del name, kwargs
        yield _RecordingSpan()


@pytest.fixture(autouse=True)
def _reset_traced_flag() -> Iterator[None]:
    Orchestrator._traced = False
    yield
    Orchestrator._traced = False


@pytest.fixture
def _patched_tracer(monkeypatch: pytest.MonkeyPatch) -> _NullTracer:
    from nengok.core import orchestrator as orch_module

    tracer = _NullTracer()
    monkeypatch.setattr(orch_module, "get_tracer", lambda: tracer)
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    return tracer


def _trace_span(span_id: str) -> TraceSpan:
    return TraceSpan(span_id=span_id, trace_id=f"t-{span_id}", name="agent")


def _anomaly(span_id: str) -> AnomalousSpan:
    return AnomalousSpan(span=_trace_span(span_id), signals=[AnomalySignal.HIGH_LATENCY])


class _RecordingState:
    def __init__(self) -> None:
        self.records: list[CycleRecord] = []
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

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        del cluster_id, result

    def record_cycle(self, record: CycleRecord) -> None:
        self.records.append(record)


class _Sampler:
    def __init__(self, spans: list[TraceSpan]) -> None:
        self._spans = spans

    def sample(self, **kwargs: object) -> list[TraceSpan]:
        del kwargs
        return self._spans


class _PassThroughFilter:
    def __init__(self, anomalies: list[AnomalousSpan]) -> None:
        self._anomalies = anomalies

    def filter(self, spans: list[TraceSpan]) -> list[AnomalousSpan]:
        del spans
        return self._anomalies


class _ExplodingClusterer:
    def __init__(self) -> None:
        self.cost_tracker: Any = None

    def cluster(self, anomalies: list[AnomalousSpan]) -> list[Cluster]:
        del anomalies
        raise RuntimeError("clusterer boom")


class _StubPromptProposer:
    def __init__(self) -> None:
        self.cost_tracker: Any = None

    def load_baseline_prompt(self, project: str | None = None) -> str:
        del project
        return "BASE"


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        min_cluster_size=1,
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        triage_enabled=False,
    )


def test_orchestrator_persists_failed_cycle_when_stage_raises(
    tmp_path: Path, _patched_tracer: _NullTracer
) -> None:
    del _patched_tracer

    orch = Orchestrator(config=_config(tmp_path))
    state = _RecordingState()
    orch._state = state
    orch._sampler = _Sampler([_trace_span("s1")])
    orch._anomaly_filter = _PassThroughFilter([_anomaly("s1")])
    orch._prompt_proposer = _StubPromptProposer()
    orch._clusterer = _ExplodingClusterer()

    with pytest.raises(RuntimeError, match="clusterer boom"):
        orch.run_once()

    assert len(state.records) == 1
    record = state.records[0]
    assert record.status is CycleStatus.FAILED
    assert record.error_message is not None
    assert "clusterer boom" in record.error_message


def test_orchestrator_persists_ok_cycle_with_zero_counts_when_no_anomalies(
    tmp_path: Path, _patched_tracer: _NullTracer
) -> None:
    del _patched_tracer

    orch = Orchestrator(config=_config(tmp_path))
    state = _RecordingState()
    orch._state = state
    orch._sampler = _Sampler([])
    orch._anomaly_filter = _PassThroughFilter([])

    result = orch.run_once()

    assert result.clusters_detected == 0
    assert len(state.records) == 1
    record = state.records[0]
    assert record.status is CycleStatus.OK
    assert record.clusters_discovered == 0
    assert record.clusters_processed == 0
    assert record.error_message is None


def test_list_cycles_between_returns_extended_columns(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    store.record_cycle(
        _record(
            "c-in-window",
            started_at=start + timedelta(days=5),
            status=CycleStatus.CIRCUIT_BROKEN,
            clusters_discovered=4,
            clusters_processed=1,
        )
    )
    store.record_cycle(
        _record(
            "c-out-of-window",
            started_at=start - timedelta(days=10),
            status=CycleStatus.OK,
        )
    )

    rows = store.list_cycles_between(since=start, until=start + timedelta(days=30))
    assert [row["cycle_id"] for row in rows] == ["c-in-window"]
    assert rows[0]["status"] == "circuit_broken"
    assert rows[0]["clusters_discovered"] == 4
