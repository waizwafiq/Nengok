"""Round-trip coverage for the experiments table on StateStore."""

from __future__ import annotations

from pathlib import Path

from nengok.core.types import ExperimentResult
from nengok.state.store import StateStore


def _result(experiment_id: str, fix_pass_rate: float) -> ExperimentResult:
    return ExperimentResult(
        experiment_name=f"{experiment_id}-fix",
        experiment_id=experiment_id,
        dataset_name="flights-schema-drift-regression",
        baseline_pass_rate=0.4,
        fix_pass_rate=fix_pass_rate,
        golden_baseline_pass_rate=0.9,
        golden_fix_pass_rate=0.95,
        per_case=[{"case_id": "c1", "passed": True}],
    )


def test_latest_experiment_returns_none_when_missing(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    assert store.latest_experiment("c-unknown") is None


def test_record_experiment_round_trip(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.record_experiment(cluster_id="c-1", result=_result("exp-1", fix_pass_rate=0.8))

    row = store.latest_experiment("c-1")
    assert row is not None
    assert row["cluster_id"] == "c-1"
    assert row["experiment_id"] == "exp-1"
    assert row["experiment_name"] == "exp-1-fix"
    assert row["dataset_name"] == "flights-schema-drift-regression"
    assert row["baseline_pass_rate"] == 0.4
    assert row["fix_pass_rate"] == 0.8
    assert row["golden_baseline_pass_rate"] == 0.9
    assert row["golden_fix_pass_rate"] == 0.95
    assert row["per_case"] == [{"case_id": "c1", "passed": True}]
    assert row["created_at"]


def test_latest_experiment_returns_most_recent_insert(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.record_experiment(cluster_id="c-1", result=_result("exp-old", fix_pass_rate=0.5))
    store.record_experiment(cluster_id="c-1", result=_result("exp-new", fix_pass_rate=0.9))

    row = store.latest_experiment("c-1")
    assert row is not None
    assert row["experiment_id"] == "exp-new"
    assert row["fix_pass_rate"] == 0.9


def test_latest_experiment_scopes_by_cluster(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.record_experiment(cluster_id="c-1", result=_result("exp-a", fix_pass_rate=0.7))
    store.record_experiment(cluster_id="c-2", result=_result("exp-b", fix_pass_rate=0.3))

    row_one = store.latest_experiment("c-1")
    row_two = store.latest_experiment("c-2")
    assert row_one is not None and row_one["experiment_id"] == "exp-a"
    assert row_two is not None and row_two["experiment_id"] == "exp-b"
