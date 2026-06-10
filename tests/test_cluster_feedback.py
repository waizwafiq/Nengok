"""Reviewer decisions land in nengok_cluster_feedback and feed the clusterer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.core.diagnoser.clusterer import Clusterer
from nengok.core.types import Cluster, ClusterStatus
from nengok.server.main import create_app
from nengok.state.store import StateStore


def _cluster(cluster_id: str, *, project: str = "travel-planner-agent") -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=f"name-{cluster_id}",
        description="d",
        status=ClusterStatus.FIX_PROPOSED,
        member_span_ids=["s-1", "s-2", "s-3"],
        exemplar_span_ids=["s-1"],
        hypothesis=None,
        created_at=now,
        updated_at=now,
        project=project,
    )


def _setup(tmp_path: Path) -> tuple[NengokConfig, StateStore, TestClient]:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    store.upsert_cluster(_cluster("c-1"))
    return config, store, TestClient(create_app(config=config))


def test_untagged_rejection_writes_fix_rejected(tmp_path: Path) -> None:
    _, store, client = _setup(tmp_path)

    response = client.post(
        "/api/v1/clusters/c-1/approvals",
        json={"decision": "rejected", "reason": "prompt edit too broad", "source": "dashboard"},
    )
    assert response.status_code == 200

    rows = store.list_cluster_feedback("travel-planner-agent")
    assert len(rows) == 1
    assert rows[0]["kind"] == "fix_rejected"
    assert rows[0]["detail"] == "prompt edit too broad"
    assert rows[0]["source"] == "dashboard"


def test_tagged_rejection_overrides_the_kind(tmp_path: Path) -> None:
    _, store, client = _setup(tmp_path)

    client.post(
        "/api/v1/clusters/c-1/approvals",
        json={
            "decision": "rejected",
            "reason": "two different bugs in one cluster",
            "source": "tui",
            "feedback_tag": "mixed_root_causes",
        },
    )

    rows = store.list_cluster_feedback("travel-planner-agent")
    assert rows[0]["kind"] == "mixed_root_causes"
    assert rows[0]["source"] == "tui"


def test_approval_and_dismissal_map_to_their_kinds(tmp_path: Path) -> None:
    _, store, client = _setup(tmp_path)

    client.post("/api/v1/clusters/c-1/approvals", json={"decision": "approved"})
    client.post("/api/v1/clusters/c-1/approvals", json={"decision": "dismissed"})

    kinds = {row["kind"] for row in store.list_cluster_feedback("travel-planner-agent", limit=10)}
    assert kinds == {"fix_approved", "cluster_dismissed"}


def test_escalation_writes_no_feedback(tmp_path: Path) -> None:
    _, store, client = _setup(tmp_path)

    client.post("/api/v1/clusters/c-1/approvals", json={"decision": "escalated"})

    assert store.list_cluster_feedback("travel-planner-agent") == []


def test_merge_wrong_detaches_spans_for_reprocessing(tmp_path: Path) -> None:
    _, store, client = _setup(tmp_path)
    store.assign_spans_to_cluster(["s-1", "s-2", "s-3"], "c-1")
    seeded = StateStore(tmp_path / "state.db")
    with seeded._connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO nengok_seen_spans (span_id, cluster_id, first_seen) VALUES (?, ?, ?)",
            [(f"s-{i}", "c-1", "2026-06-10T00:00:00+00:00") for i in (1, 2, 3)],
        )

    response = client.post(
        "/api/v1/clusters/c-1/feedback/merge-wrong",
        json={"span_ids": ["s-2", "s-3"], "reason": "those spans belong to a different bug"},
    )
    assert response.status_code == 200
    assert response.json()["detached_count"] == 2

    rows = store.list_cluster_feedback("travel-planner-agent")
    assert rows[0]["kind"] == "merge_wrong"

    clusters = store.list_clusters()
    import json as json_module

    members = json_module.loads(clusters[0]["member_spans_json"])
    assert members == ["s-1"]

    with seeded._connect() as conn:
        remaining = {r["span_id"] for r in conn.execute("SELECT span_id FROM nengok_seen_spans").fetchall()}
    assert "s-2" not in remaining
    assert "s-3" not in remaining


def test_merge_wrong_rejects_foreign_span_ids(tmp_path: Path) -> None:
    _, _, client = _setup(tmp_path)
    response = client.post(
        "/api/v1/clusters/c-1/feedback/merge-wrong",
        json={"span_ids": ["not-a-member"]},
    )
    assert response.status_code == 400


def test_clusterer_prompt_carries_redacted_past_corrections(tmp_path: Path) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    feedback = [
        {
            "kind": "mixed_root_causes",
            "cluster_name": "flights-schema-drift",
            "detail": "contact user@example.com about span A vs span B",
        }
    ]
    captured: dict[str, str] = {}

    def fake_gemini(prompt: str) -> str:
        captured["prompt"] = prompt
        import json as json_module

        return json_module.dumps(
            {"clusters": [{"name": "one", "description": "d", "member_span_ids": ["s1"]}]}
        )

    from nengok.core.types import AnomalousSpan, AnomalySignal, TraceSpan

    anomalies = [
        AnomalousSpan(
            span=TraceSpan(span_id="s1", trace_id="t1", name="agent"),
            signals=[AnomalySignal.ERROR_STATUS],
        )
    ]
    Clusterer(config=config, gemini_call=fake_gemini, feedback=feedback).cluster(anomalies)

    assert "Past corrections from human reviewers" in captured["prompt"]
    assert "flights-schema-drift" in captured["prompt"]
    assert "mixing different root causes" in captured["prompt"]
    assert "user@example.com" not in captured["prompt"]
