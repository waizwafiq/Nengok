"""HTTP coverage for the ?project= filter on clusters and overview."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.core.types import Cluster, ClusterStatus
from nengok.server.main import create_app
from nengok.state.store import StateStore


def _cluster(cluster_id: str, project: str) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=f"name-{cluster_id}",
        description="d",
        status=ClusterStatus.OPEN,
        member_span_ids=[f"s-{cluster_id}"],
        exemplar_span_ids=[f"s-{cluster_id}"],
        hypothesis=None,
        created_at=now,
        updated_at=now,
        project=project,
    )


def _client(tmp_path: Path) -> TestClient:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    store.upsert_cluster(_cluster("c-a", "travel-planner-agent"))
    store.upsert_cluster(_cluster("c-b", "qa-agent"))
    return TestClient(create_app(config=config))


def test_clusters_filter_by_project(tmp_path: Path) -> None:
    client = _client(tmp_path)

    everything = client.get("/api/v1/clusters").json()
    assert {c["cluster_id"] for c in everything} == {"c-a", "c-b"}

    travel_only = client.get("/api/v1/clusters", params={"project": "travel-planner-agent"}).json()
    assert [c["cluster_id"] for c in travel_only] == ["c-a"]
    assert travel_only[0]["project"] == "travel-planner-agent"


def test_overview_scopes_cluster_counts_by_project(tmp_path: Path) -> None:
    client = _client(tmp_path)

    unscoped = client.get("/api/v1/dashboard/overview").json()
    assert unscoped["cluster_counts"]["open"] == 2

    scoped = client.get("/api/v1/dashboard/overview", params={"project": "qa-agent"}).json()
    assert scoped["cluster_counts"]["open"] == 1
