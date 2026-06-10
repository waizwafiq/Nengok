"""
Orchestrator gating on the triage verdict.

`run_triage` and `triage_disabled_reason` are monkeypatched on the
orchestrator module so these tests run without google-adk or Node
installed. The agent itself is covered in test_triage_agent.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from nengok.agents.triage import TriageVerdict
from nengok.config import NengokConfig
from nengok.core import orchestrator as orch_module
from nengok.core.orchestrator import Orchestrator
from nengok.core.types import (
    AnomalousSpan,
    Cluster,
    ClusterStatus,
    CycleRecord,
    CycleStatus,
    ExperimentResult,
    TraceSpan,
)


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


@pytest.fixture(autouse=True)
def _patched_tracer(monkeypatch: pytest.MonkeyPatch) -> _NullTracer:
    tracer = _NullTracer()
    monkeypatch.setattr(orch_module, "get_tracer", lambda: tracer)
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    return tracer


class _RecordingState:
    def __init__(self) -> None:
        self.records: list[CycleRecord] = []

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
        del cluster_id, status

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        del cluster_id, result

    def record_cycle(self, record: CycleRecord) -> None:
        self.records.append(record)


class _RecordingSampler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def sample(
        self,
        *,
        project_identifier: str | None = None,
        window_minutes: int | None = None,
    ) -> list[TraceSpan]:
        self.calls.append({"project_identifier": project_identifier, "window_minutes": window_minutes})
        return []


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        min_cluster_size=1,
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        triage_enabled=True,
    )


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: TriageVerdict,
) -> tuple[Orchestrator, _RecordingState, _RecordingSampler]:
    monkeypatch.setattr(orch_module, "triage_disabled_reason", lambda _cfg: None)
    monkeypatch.setattr(orch_module, "run_triage", lambda _cfg: verdict)
    orch = Orchestrator(config=_config(tmp_path))
    state = _RecordingState()
    sampler = _RecordingSampler()
    orch._state = state
    orch._sampler = sampler
    return orch, state, sampler


def test_skip_verdict_short_circuits_before_observer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = TriageVerdict(
        investigate=False,
        project="travel-planner-agent",
        window_minutes=15,
        reason="window is quiet",
    )
    orch, state, sampler = _build(tmp_path, monkeypatch, verdict)

    result = orch.run_once()

    assert sampler.calls == []
    assert result.clusters_detected == 0
    assert len(state.records) == 1
    assert state.records[0].status is CycleStatus.SKIPPED_BY_TRIAGE


def test_investigate_verdict_narrows_observer_to_project_and_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verdict = TriageVerdict(
        investigate=True,
        project="other-project",
        window_minutes=30,
        reason="latency outliers",
    )
    orch, state, sampler = _build(tmp_path, monkeypatch, verdict)

    orch.run_once()

    assert sampler.calls == [{"project_identifier": "other-project", "window_minutes": 30}]
    assert state.records[0].status is CycleStatus.OK


def test_triage_off_calls_sampler_without_narrowing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _explode(_cfg: NengokConfig) -> TriageVerdict:
        raise AssertionError("run_triage must not be called when triage is disabled")

    monkeypatch.setattr(orch_module, "run_triage", _explode)
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
    state = _RecordingState()
    sampler = _RecordingSampler()
    orch._state = state
    orch._sampler = sampler

    orch.run_once()

    assert sampler.calls == [{"project_identifier": None, "window_minutes": None}]
    assert state.records[0].status is CycleStatus.OK


def test_triage_enabled_but_unavailable_warns_once_and_runs_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(orch_module, "triage_disabled_reason", lambda _cfg: "the adk extra is not installed")

    def _explode(_cfg: NengokConfig) -> TriageVerdict:
        raise AssertionError("run_triage must not be called when the extra is missing")

    monkeypatch.setattr(orch_module, "run_triage", _explode)

    with caplog.at_level("WARNING"):
        orch = Orchestrator(config=_config(tmp_path))
    orch._state = _RecordingState()
    orch._sampler = _RecordingSampler()

    orch.run_once()

    warnings = [rec for rec in caplog.records if "cannot run" in rec.getMessage()]
    assert len(warnings) == 1
