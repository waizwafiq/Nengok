"""Aggregation coverage for StateStore.dashboard_overview."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nengok.core.types import (
    Cluster,
    ClusterStatus,
    ExperimentResult,
    RootCauseHypothesis,
)
from nengok.state.store import StateStore


def _hypothesis() -> RootCauseHypothesis:
    return RootCauseHypothesis(
        summary="s",
        expected_behavior="e",
        actual_behavior="a",
        likely_cause="c",
        implicated_tools=["t"],
    )


def _cluster(cluster_id: str, status: ClusterStatus, *, created_at: datetime) -> Cluster:
    return Cluster(
        cluster_id=cluster_id,
        name=cluster_id,
        description="d",
        status=status,
        member_span_ids=[f"{cluster_id}-s1"],
        exemplar_span_ids=[f"{cluster_id}-s1"],
        hypothesis=_hypothesis(),
        created_at=created_at,
        updated_at=created_at,
    )


def _result(case_count: int, fix_pass_rate: float) -> ExperimentResult:
    return ExperimentResult(
        experiment_name="exp",
        experiment_id="exp-1",
        dataset_name="ds",
        baseline_pass_rate=0.5,
        fix_pass_rate=fix_pass_rate,
        golden_baseline_pass_rate=0.9,
        golden_fix_pass_rate=0.95,
        per_case=[{"case_id": f"c{i}", "passed": True} for i in range(case_count)],
    )


def test_overview_returns_zeroed_metrics_on_empty_store(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    overview = store.dashboard_overview()

    assert overview["cluster_counts"] == {
        "open": 0,
        "diagnosed": 0,
        "fix_proposed": 0,
        "approved": 0,
        "rejected": 0,
        "dismissed": 0,
        "escalated": 0,
    }
    assert overview["close_rate"] == 0.0
    assert overview["regression_test_count"] == 0
    assert overview["mttd_seconds"] is None
    assert overview["mttr_seconds"] is None
    assert overview["fix_pass_rate_30d"] is None
    assert overview["gemini_tokens_used_30d"] == 0
    assert overview["gemini_dollars_used_30d"] == 0.0
    assert overview["gemini_spend_sparkline_30d"] == []


def test_overview_aggregates_status_counts_and_close_rate(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)
    store.upsert_cluster(_cluster("c-open", ClusterStatus.OPEN, created_at=now))
    store.upsert_cluster(_cluster("c-diag", ClusterStatus.DIAGNOSED, created_at=now))
    store.upsert_cluster(_cluster("c-app", ClusterStatus.APPROVED, created_at=now))
    store.upsert_cluster(_cluster("c-esc", ClusterStatus.ESCALATED, created_at=now))

    overview = store.dashboard_overview()
    counts = overview["cluster_counts"]
    assert counts["open"] == 1
    assert counts["diagnosed"] == 1
    assert counts["approved"] == 1
    assert counts["escalated"] == 1
    assert overview["close_rate"] == 1 / 4


def test_overview_computes_mttd_and_mttr_in_seconds(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    first_seen = datetime.now(UTC) - timedelta(seconds=600)
    diagnosed = first_seen + timedelta(seconds=120)
    cluster = _cluster("c-1", ClusterStatus.DIAGNOSED, created_at=diagnosed)
    store.upsert_cluster(cluster, first_seen=first_seen)
    store.mark_status("c-1", ClusterStatus.APPROVED)
    store.record_approval(cluster_id="c-1", decision="approved", reviewer=None, reason=None)

    overview = store.dashboard_overview()
    assert overview["mttd_seconds"] is not None
    assert 110 <= overview["mttd_seconds"] <= 130
    assert overview["mttr_seconds"] is not None
    assert overview["mttr_seconds"] >= 0


def test_overview_sums_regression_cases_from_latest_experiment_per_cluster(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.record_experiment(cluster_id="c-1", result=_result(case_count=3, fix_pass_rate=0.8))
    store.record_experiment(cluster_id="c-1", result=_result(case_count=5, fix_pass_rate=0.9))
    store.record_experiment(cluster_id="c-2", result=_result(case_count=4, fix_pass_rate=0.7))

    overview = store.dashboard_overview()
    assert overview["regression_test_count"] == 9
    assert overview["fix_pass_rate_30d"] is not None
    assert 0.7 <= overview["fix_pass_rate_30d"] <= 0.9


def test_overview_aggregates_gemini_spend_and_sparkline(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(UTC)
    store.record_cycle_usage(
        cycle_id="c-1",
        started_at=now - timedelta(days=2),
        ended_at=now - timedelta(days=2),
        gemini_tokens=4_000,
        gemini_dollars=0.12,
    )
    store.record_cycle_usage(
        cycle_id="c-2",
        started_at=now - timedelta(days=1),
        ended_at=now - timedelta(days=1),
        gemini_tokens=6_000,
        gemini_dollars=0.18,
    )
    store.record_cycle_usage(
        cycle_id="c-3",
        started_at=now - timedelta(days=1, hours=2),
        ended_at=now - timedelta(days=1),
        gemini_tokens=2_000,
        gemini_dollars=0.05,
    )

    overview = store.dashboard_overview()
    assert overview["gemini_tokens_used_30d"] == 12_000
    assert overview["gemini_dollars_used_30d"] == pytest.approx(0.35)

    sparkline = overview["gemini_spend_sparkline_30d"]
    assert len(sparkline) == 2
    assert sparkline[0]["day"] < sparkline[1]["day"]
    assert sparkline[-1]["tokens"] == 8_000
    assert sparkline[-1]["dollars"] == pytest.approx(0.23)
