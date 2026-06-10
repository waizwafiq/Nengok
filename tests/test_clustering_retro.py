"""Retro pass: metrics math, proposed advice, activation, failure isolation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from nengok import cli as cli_module
from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import _build_clusterer_prompt
from nengok.core.improver.retro import ClusteringRetro, compute_metrics
from nengok.core.observer.redactor import Redactor
from nengok.core.types import AnomalousSpan, AnomalySignal, Cluster, ClusterStatus, TraceSpan
from nengok.state.store import StateStore


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def _cluster(cluster_id: str, status: ClusterStatus = ClusterStatus.DIAGNOSED) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=f"name-{cluster_id}",
        description="d",
        status=status,
        member_span_ids=[f"s-{cluster_id}-1", f"s-{cluster_id}-2"],
        exemplar_span_ids=[f"s-{cluster_id}-1"],
        hypothesis=None,
        created_at=now,
        updated_at=now,
        project="travel-planner-agent",
    )


_ADVICE_JSON = json.dumps(
    {
        "observations": ["reviewers keep splitting flights clusters"],
        "prompt_amendment": "Never merge flights and weather symptoms into one cluster.",
        "expected_effect": "fewer mixed_root_causes rejections",
    }
)


def test_compute_metrics_on_canned_data() -> None:
    clusters = [
        {"status": "escalated", "member_spans_json": json.dumps(["a", "b", "c"])},
        {"status": "approved", "member_spans_json": json.dumps(["d"])},
    ]
    feedback = [{"kind": "mixed_root_causes"}, {"kind": "fix_approved"}, {"kind": "fix_rejected"}]
    cycles = [
        {"clusters_discovered": 4, "clusters_merged": 2, "gemini_tokens": 1000},
        {"clusters_discovered": 6, "clusters_merged": 3, "gemini_tokens": 3000},
    ]
    links = [{"link_id": "l1"}]

    metrics = compute_metrics(clusters=clusters, feedback=feedback, cycles=cycles, links=links)

    assert metrics["duplicate_cluster_rate"] == 0.5
    assert metrics["rejection_counts_by_kind"]["mixed_root_causes"] == 1
    assert metrics["escalation_rate"] == 0.5
    assert metrics["median_cluster_size"] == 2
    assert metrics["gemini_tokens_per_cycle"] == 2000.0
    assert metrics["cross_agent_links"] == 1


def test_retro_records_proposed_advice_and_report(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    store.upsert_cluster(_cluster("c-1"))
    store.record_cluster_feedback(
        cluster_id="c-1", kind="mixed_root_causes", detail="two bugs in one", source="dashboard"
    )

    retro = ClusteringRetro(config=config, store=store, gemini_call=lambda _: _ADVICE_JSON)
    result = retro.run(project="travel-planner-agent")

    rows = store.list_clustering_advice(status="proposed")
    assert len(rows) == 1
    assert rows[0]["advice_id"] == result.advice_id
    assert "Never merge flights" in rows[0]["prompt_amendment"]

    report = Path(result.report_path)
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Clustering retro" in text
    assert "Never merge flights" in text
    assert "proposed" in text


def test_activation_flips_status_and_reaches_the_clusterer_prompt(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    store.upsert_cluster(_cluster("c-1"))

    retro = ClusteringRetro(config=config, store=store, gemini_call=lambda _: _ADVICE_JSON)
    result = retro.run(project="travel-planner-agent")

    assert store.get_active_advice("travel-planner-agent") is None
    activated = store.activate_clustering_advice(advice_id=result.advice_id, decided_by="alice")
    assert activated is not None
    assert activated["status"] == "active"
    assert activated["decided_by"] == "alice"

    active = store.get_active_advice("travel-planner-agent")
    assert active is not None

    anomalies = [
        AnomalousSpan(
            span=TraceSpan(span_id="s1", trace_id="t1", name="agent"),
            signals=[AnomalySignal.ERROR_STATUS],
        )
    ]
    prompt = _build_clusterer_prompt(
        anomalies,
        2000,
        redactor=Redactor.from_config(config),
        advice_amendment=active["prompt_amendment"],
    )
    assert "Operator-approved clustering guidance" in prompt
    assert "Never merge flights" in prompt


def test_second_activation_retires_the_first(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)

    first = store.record_clustering_advice(
        project="travel-planner-agent", prompt_amendment="first", metrics_json=None
    )
    second = store.record_clustering_advice(
        project="travel-planner-agent", prompt_amendment="second", metrics_json=None
    )

    store.activate_clustering_advice(advice_id=first, decided_by="alice")
    store.activate_clustering_advice(advice_id=second, decided_by="bob")

    rows = {row["advice_id"]: row["status"] for row in store.list_clustering_advice()}
    assert rows[first] == "retired"
    assert rows[second] == "active"
    active = store.get_active_advice("travel-planner-agent")
    assert active is not None
    assert active["prompt_amendment"] == "second"


def test_retro_failure_never_breaks_the_watch_loop(tmp_path: Path, monkeypatch) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        improve_every_cycles=1,
    )

    class _ExplodingRetro:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, **kwargs: object) -> None:
            raise RuntimeError("retro blew up")

    import nengok.core.improver.retro as retro_module

    monkeypatch.setattr(retro_module, "ClusteringRetro", _ExplodingRetro)

    cli_module._maybe_run_retro(config=config, completed_cycles=1)
