"""
Fallback behavior when the triage agent dies mid-cycle.

Each wrapped exception type must produce an investigate-everything
verdict, a `triage_path=fallback` log line, and a cycle that still
runs the deterministic pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

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
from nengok.errors import OptionalDependencyError, TriageError
from nengok.phoenix.mcp import MCPError
from nengok.utils.gemini import GeminiQuotaError


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


def _validation_error() -> ValidationError:
    try:
        TriageVerdict.model_validate({})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected the empty payload to fail validation")


def _wrapped_exceptions() -> list[BaseException]:
    return [
        _validation_error(),
        TimeoutError("triage timed out"),
        MCPError("npx died"),
        GeminiQuotaError("quota exhausted", retry_after_seconds=None, quota_id=None),
        OptionalDependencyError("missing", install_hint='pip install "nengok[adk]"'),
        TriageError("agent fell over"),
    ]


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        project_identifier="travel-planner-agent",
        triage_enabled=True,
        triage_lookback_minutes=20,
    )


@pytest.mark.parametrize("exc", _wrapped_exceptions(), ids=lambda e: type(e).__name__)
def test_triage_failure_falls_back_and_cycle_still_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc: BaseException,
) -> None:
    monkeypatch.setattr(orch_module, "triage_disabled_reason", lambda _cfg: None)

    def _raise(_cfg: NengokConfig) -> TriageVerdict:
        raise exc

    monkeypatch.setattr(orch_module, "run_triage", _raise)

    orch = Orchestrator(config=_config(tmp_path))
    state = _RecordingState()
    sampler = _RecordingSampler()
    orch._state = state
    orch._sampler = sampler

    with caplog.at_level("INFO"):
        result = orch.run_once()

    assert result.clusters_detected == 0
    assert state.records[0].status is CycleStatus.OK
    assert sampler.calls == [{"project_identifier": "travel-planner-agent", "window_minutes": 20}]

    decided = [rec for rec in caplog.records if getattr(rec, "event", None) == "triage_decided"]
    assert len(decided) == 1
    assert decided[0].triage_path == "fallback"
    assert decided[0].reason == "triage_fallback"
    assert "triage_path=fallback" in decided[0].getMessage()
