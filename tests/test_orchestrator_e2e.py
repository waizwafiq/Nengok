"""
E2E orchestrator tests: wire real Hypothesizer / TestGenerator / PromptProposer
with injected fake Gemini callables and verify happy-path completion and Gemini
error propagation.

Fake shapes copied from test_orchestrator_tracing.py.  All peripheral stages
(_Sampler, _AnomalyFilter, _State, _Clusterer, _ExperimentRunner,
_ArtifactWriter) remain lightweight fakes so only the Gemini-calling stages
carry real implementation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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
from nengok.utils.gemini import GeminiAuthError, GeminiQuotaError, InvalidGeminiModelError

# ---------------------------------------------------------------------------
# Fake Gemini callables
# ---------------------------------------------------------------------------

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


def _raiser(exc: Exception) -> Callable[[str], str]:
    def _fn(_prompt: str) -> str:
        raise exc

    return _fn


# ---------------------------------------------------------------------------
# Fake peripheral stages
# ---------------------------------------------------------------------------


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
        hypothesis=None,
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
        self.experiments: list[str] = []

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

    def upsert_cluster(self, cluster: Cluster, *, first_seen: datetime | None = None) -> None:
        del cluster, first_seen

    def mark_status(self, cluster_id: str, status: ClusterStatus) -> None:
        self.statuses.append((cluster_id, status))

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        self.experiments.append(cluster_id)

    def record_cycle(self, _record: object) -> None:
        return


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_traced_flag() -> Iterator[None]:
    Orchestrator._traced = False
    yield
    Orchestrator._traced = False


@pytest.fixture
def patched_tracer(monkeypatch: pytest.MonkeyPatch) -> _NullTracer:
    tracer = _NullTracer()
    monkeypatch.setattr(orch_module, "get_tracer", lambda: tracer)
    monkeypatch.setattr(orch_module, "register_meta_tracer", lambda: None)
    return tracer


# ---------------------------------------------------------------------------
# Build helper
# ---------------------------------------------------------------------------


def _build_orchestrator(
    tmp_path: Path,
    *,
    clusters: list[Cluster],
    hypothesizer_gemini: Callable[[str], str] = lambda _: _HYPOTHESIS_JSON,
    test_gen_gemini: Callable[[str], str] = lambda _: _CASES_JSON,
    proposer_gemini: Callable[[str], str] = lambda _: _PROPOSAL_JSON,
) -> tuple[Orchestrator, _State, _ArtifactWriter]:
    config = NengokConfig.load(
        min_cluster_size=1,
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        project_identifier="travel-planner-agent",
        triage_enabled=False,
    )
    orch = Orchestrator(config=config)
    anomalies = [_make_anomaly(c.cluster_id) for c in clusters]
    state = _State()
    writer = _ArtifactWriter()

    orch._sampler = _Sampler([_make_trace_span(c.cluster_id) for c in clusters])
    orch._anomaly_filter = _AnomalyFilter(anomalies)
    orch._state = state
    orch._clusterer = _Clusterer(clusters)
    orch._hypothesizer = Hypothesizer(config=config, gemini_call=hypothesizer_gemini)
    orch._test_generator = TestGenerator(config=config, gemini_call=test_gen_gemini)
    orch._prompt_proposer = PromptProposer(config=config, gemini_call=proposer_gemini)
    orch._experiment_runner = _ExperimentRunner()
    orch._artifact_writer = writer

    return orch, state, writer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_with_real_stages(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer
    cluster = _make_cluster("c-1")
    orch, state, writer = _build_orchestrator(tmp_path, clusters=[cluster])

    result = orch.run_once()

    assert result.fixes_proposed == 1
    assert result.clusters_detected == 1
    assert result.escalations == 0
    assert len(writer.writes) == 1
    assert (cluster.cluster_id, ClusterStatus.FIX_PROPOSED) in state.statuses


def test_gemini_auth_error_propagates_from_hypothesizer(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer
    cluster = _make_cluster("c-1")
    orch, _, _ = _build_orchestrator(
        tmp_path,
        clusters=[cluster],
        hypothesizer_gemini=_raiser(GeminiAuthError("bad key")),
    )

    with pytest.raises(GeminiAuthError):
        orch.run_once()


def test_gemini_quota_error_propagates_from_hypothesizer(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer
    cluster = _make_cluster("c-1")
    orch, _, _ = _build_orchestrator(
        tmp_path,
        clusters=[cluster],
        hypothesizer_gemini=_raiser(GeminiQuotaError("quota exceeded")),
    )

    with pytest.raises(GeminiQuotaError):
        orch.run_once()


def test_invalid_model_error_propagates_from_hypothesizer(
    tmp_path: Path, patched_tracer: _NullTracer
) -> None:
    del patched_tracer
    cluster = _make_cluster("c-1")
    orch, _, _ = _build_orchestrator(
        tmp_path,
        clusters=[cluster],
        hypothesizer_gemini=_raiser(InvalidGeminiModelError("no such model")),
    )

    with pytest.raises(InvalidGeminiModelError):
        orch.run_once()


def test_gemini_error_in_test_generator_propagates(tmp_path: Path, patched_tracer: _NullTracer) -> None:
    del patched_tracer
    cluster = _make_cluster("c-1")
    orch, _, _ = _build_orchestrator(
        tmp_path,
        clusters=[cluster],
        hypothesizer_gemini=lambda _: _HYPOTHESIS_JSON,
        test_gen_gemini=_raiser(GeminiAuthError("bad key in test gen")),
    )

    with pytest.raises(GeminiAuthError):
        orch.run_once()
