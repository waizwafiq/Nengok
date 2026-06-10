"""HTTP coverage for /api/v1/clusters/{id}/links."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.core.types import Cluster, ClusterStatus
from nengok.server.main import create_app
from nengok.state.store import StateStore


def _cluster(cluster_id: str, name: str, project: str) -> Cluster:
    now = datetime.now(UTC)
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        description="d",
        status=ClusterStatus.DIAGNOSED,
        member_span_ids=[f"s-{cluster_id}"],
        exemplar_span_ids=[f"s-{cluster_id}"],
        hypothesis=None,
        created_at=now,
        updated_at=now,
        project=project,
    )


def test_links_endpoint_returns_sibling_summary(tmp_path: Path) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    store.upsert_cluster(_cluster("c-travel", "flights-schema-drift", "travel-planner-agent"))
    store.upsert_cluster(_cluster("c-qa", "qa-flight-status-garbled", "qa-agent"))
    store.insert_cluster_link(
        cluster_id_a="c-travel",
        cluster_id_b="c-qa",
        confidence=0.91,
        rationale="both consume tool.flights.search",
    )

    client = TestClient(create_app(config=config))

    response = client.get("/api/v1/clusters/c-travel/links")
    assert response.status_code == 200
    links = response.json()
    assert len(links) == 1
    assert links[0]["linked_cluster_id"] == "c-qa"
    assert links[0]["linked_name"] == "qa-flight-status-garbled"
    assert links[0]["linked_project"] == "qa-agent"
    assert links[0]["confidence"] == 0.91

    mirrored = client.get("/api/v1/clusters/c-qa/links").json()
    assert mirrored[0]["linked_cluster_id"] == "c-travel"

    missing = client.get("/api/v1/clusters/nope/links")
    assert missing.status_code == 404
