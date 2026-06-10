"""Deterministic scorer tests: pairwise P/R/F1 over canned clusterer output."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nengok.core.evaluators.clustering_score import (
    load_clustering_golden,
    pairwise_scores,
    score_clusters,
)
from nengok.core.types import Cluster, ClusterStatus


def _cluster(name: str, span_ids: list[str]) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=f"c-{name}",
        name=name,
        description="d",
        status=ClusterStatus.OPEN,
        member_span_ids=span_ids,
        exemplar_span_ids=span_ids[:5],
        hypothesis=None,
        created_at=now,
        updated_at=now,
    )


def test_perfect_grouping_scores_one() -> None:
    expected = {"a": "x", "b": "x", "c": "y", "d": "y"}
    predicted = {"a": "p1", "b": "p1", "c": "p2", "d": "p2"}
    score = pairwise_scores(predicted, expected)
    assert score.precision == 1.0
    assert score.recall == 1.0
    assert score.f1 == 1.0
    assert score.span_count == 4


def test_everything_in_one_cluster_has_full_recall_low_precision() -> None:
    expected = {"a": "x", "b": "x", "c": "y", "d": "y"}
    predicted = {"a": "p", "b": "p", "c": "p", "d": "p"}
    score = pairwise_scores(predicted, expected)
    assert score.recall == 1.0
    assert score.precision == pytest.approx(2 / 6, abs=1e-4)
    assert 0.0 < score.f1 < 1.0


def test_fully_split_prediction_has_zero_recall() -> None:
    expected = {"a": "x", "b": "x"}
    predicted = {"a": "p1", "b": "p2"}
    score = pairwise_scores(predicted, expected)
    assert score.precision == 0.0
    assert score.recall == 0.0
    assert score.f1 == 0.0


def test_dropped_spans_cost_recall() -> None:
    expected = {"a": "x", "b": "x", "c": "x"}
    predicted = {"a": "p", "b": "p"}
    score = pairwise_scores(predicted, expected)
    assert score.recall == pytest.approx(1 / 3, abs=1e-4)
    assert score.precision == 1.0


def test_score_clusters_flattens_real_cluster_output() -> None:
    expected = {"a": "x", "b": "x", "c": "y"}
    clusters = [_cluster("alpha", ["a", "b"]), _cluster("beta", ["c"])]
    score = score_clusters(clusters, expected)
    assert score.f1 == 1.0


def test_score_amendment_against_golden_with_fake_gemini(tmp_path) -> None:
    import json

    from nengok.config import NengokConfig
    from nengok.core.improver.retro import score_amendment_against_golden

    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    _, expected = load_clustering_golden()
    by_label: dict[str, list[str]] = {}
    for span_id, label in expected.items():
        by_label.setdefault(label, []).append(span_id)

    prompts: list[str] = []

    def perfect_gemini(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "clusters": [
                    {"name": label, "description": "d", "member_span_ids": ids}
                    for label, ids in by_label.items()
                ]
            }
        )

    score = score_amendment_against_golden(config, "Split mixed clusters.", gemini_call=perfect_gemini)
    assert score.f1 == 1.0
    assert "Split mixed clusters." in prompts[0]


def test_apply_golden_scores_flags_a_regressing_amendment(tmp_path) -> None:
    import json

    from nengok.config import NengokConfig
    from nengok.core.evaluators.clustering_score import ClusteringScore
    from nengok.core.improver.retro import ClusteringRetro, apply_golden_scores
    from nengok.state.store import StateStore

    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    advice_json = json.dumps(
        {
            "observations": ["o"],
            "prompt_amendment": "amendment",
            "expected_effect": "e",
        }
    )
    retro = ClusteringRetro(config=config, store=store, gemini_call=lambda _: advice_json)
    result = retro.run(project="travel-planner-agent")

    current = ClusteringScore(precision=0.9, recall=0.9, f1=0.9, span_count=30)
    proposed = ClusteringScore(precision=0.5, recall=0.5, f1=0.5, span_count=30)
    recommended = apply_golden_scores(store=store, result=result, current=current, proposed=proposed)

    assert recommended is False
    row = store.list_clustering_advice()[0]
    golden = json.loads(row["metrics_json"])["golden"]
    assert golden["recommended"] is False
    assert golden["current_f1"] == 0.9

    from pathlib import Path

    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "Golden-set scores" in report
    assert "not recommended" in report


def test_overview_exposes_clustering_quality(tmp_path) -> None:
    import json

    from nengok.config import NengokConfig
    from nengok.core.types import CycleRecord, CycleStatus
    from nengok.state.store import StateStore

    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    store.record_cycle(
        CycleRecord(
            cycle_id="cy-1",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            status=CycleStatus.OK,
            clusters_discovered=4,
            clusters_merged=2,
        )
    )
    advice_id = store.record_clustering_advice(
        project=None,
        prompt_amendment="a",
        metrics_json=json.dumps({"golden": {"current_f1": 0.83}}),
    )
    del advice_id

    quality = store.dashboard_overview()["clustering_quality"]
    assert quality["latest_golden_f1"] == 0.83
    assert len(quality["duplicate_rate_trend"]) == 1
    assert quality["duplicate_rate_trend"][0]["rate"] == 0.5


def test_golden_set_loads_with_expected_shape() -> None:
    anomalies, expected = load_clustering_golden()
    assert 25 <= len(anomalies) <= 40
    assert set(expected) == {a.span.span_id for a in anomalies}
    labels = set(expected.values())
    assert {
        "flights-schema-drift",
        "weather-unit-mismatch",
        "hotels-timeout",
        "qa-empty-retrieval-context",
        "qa-wrong-snippet-attribution",
    } == labels
