"""HTTP and store coverage for the approval audit log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.core.types import Cluster, ClusterStatus
from nengok.server.main import create_app
from nengok.server.routes.approvals import (
    ANONYMOUS_REVIEWER,
    REVIEWER_ENV_VAR,
    resolve_reviewer,
)
from nengok.state.store import StateStore


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def _seed_cluster(store: StateStore, cluster_id: str) -> None:
    now = datetime.now(UTC)
    store.upsert_cluster(
        Cluster(
            cluster_id=cluster_id,
            name=cluster_id,
            description="",
            status=ClusterStatus.DIAGNOSED,
            member_span_ids=[],
            exemplar_span_ids=[],
            created_at=now,
            updated_at=now,
        )
    )


def test_post_cluster_approval_records_reviewer_and_reason(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    response = client.post(
        "/api/v1/clusters/c-1/approvals",
        json={"decision": "approved", "reviewer": "alice", "reason": "looks fine"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cluster_id"] == "c-1"
    assert body["status"] == "approved"
    assert body["reviewer"] == "alice"
    assert body["reviewer_source"] == "request"

    listing = client.get("/api/v1/clusters/c-1/approvals").json()
    assert len(listing) == 1
    assert listing[0]["reviewer"] == "alice"
    assert listing[0]["reason"] == "looks fine"
    assert listing[0]["decision"] == "approved"


def test_post_to_missing_cluster_returns_404(tmp_path: Path) -> None:
    config = _config(tmp_path)
    StateStore(config.state_db_path)
    client = TestClient(create_app(config=config))

    response = client.post(
        "/api/v1/clusters/nope/approvals",
        json={"decision": "approved", "reviewer": "alice"},
    )
    assert response.status_code == 404


def test_get_cluster_approvals_returns_newest_first(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    for index in range(3):
        client.post(
            "/api/v1/clusters/c-1/approvals",
            json={"decision": "approved", "reviewer": f"r-{index}", "reason": None},
        )

    rows = client.get("/api/v1/clusters/c-1/approvals").json()
    assert [row["reviewer"] for row in rows] == ["r-2", "r-1", "r-0"]


def test_global_approval_feed_paginates_via_before_cursor(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    for index in range(5):
        client.post(
            "/api/v1/clusters/c-1/approvals",
            json={"decision": "approved", "reviewer": f"r-{index}"},
        )

    first_page = client.get("/api/v1/approvals", params={"limit": 2}).json()
    assert [row["reviewer"] for row in first_page] == ["r-4", "r-3"]

    second_page = client.get(
        "/api/v1/approvals",
        params={"limit": 2, "before": first_page[-1]["approval_id"]},
    ).json()
    assert [row["reviewer"] for row in second_page] == ["r-2", "r-1"]


def test_legacy_post_routes_through_record_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    response = client.post(
        "/api/v1/approvals",
        json={
            "cluster_id": "c-1",
            "decision": "rejected",
            "decided_by": "alice",
            "notes": "no.",
        },
    )
    assert response.status_code == 200

    rows = client.get("/api/v1/clusters/c-1/approvals").json()
    assert rows[0]["reviewer"] == "alice"
    assert rows[0]["reason"] == "no."
    assert rows[0]["decision"] == "rejected"


def test_escalated_decision_promotes_cluster_status(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    response = client.post(
        "/api/v1/clusters/c-1/approvals",
        json={"decision": "escalated", "reviewer": "alice", "reason": "needs human"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == ClusterStatus.ESCALATED.value


def test_get_reviewer_falls_back_to_anonymous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "nengok.server.routes.approvals.REVIEWER_FILE_PATH",
        tmp_path / "no-reviewer.txt",
    )
    config = _config(tmp_path)
    StateStore(config.state_db_path)
    client = TestClient(create_app(config=config))

    body = client.get("/api/v1/reviewer").json()
    assert body == {"reviewer": ANONYMOUS_REVIEWER, "source": "fallback"}


def test_resolve_reviewer_prefers_file_then_env_then_anonymous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = tmp_path / "reviewer.txt"
    monkeypatch.setattr("nengok.server.routes.approvals.REVIEWER_FILE_PATH", file_path)
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)

    assert resolve_reviewer(None) == (ANONYMOUS_REVIEWER, "fallback")

    monkeypatch.setenv(REVIEWER_ENV_VAR, "  alice  ")
    assert resolve_reviewer(None) == ("alice", "env")

    file_path.write_text(" charlie\n", encoding="utf-8")
    assert resolve_reviewer(None) == ("charlie", "file")

    assert resolve_reviewer(" bob ") == ("bob", "request")


def test_anonymous_path_records_when_no_identity_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(REVIEWER_ENV_VAR, raising=False)
    monkeypatch.setattr(
        "nengok.server.routes.approvals.REVIEWER_FILE_PATH",
        tmp_path / "no-reviewer.txt",
    )
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1")
    client = TestClient(create_app(config=config))

    response = client.post(
        "/api/v1/clusters/c-1/approvals",
        json={"decision": "approved"},
    )
    assert response.status_code == 200
    rows = client.get("/api/v1/clusters/c-1/approvals").json()
    assert rows[0]["reviewer"] == ANONYMOUS_REVIEWER
