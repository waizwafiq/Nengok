"""HTTP coverage for /api/v1/dashboard/overview."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.server.main import create_app


def _client(tmp_path: Path) -> TestClient:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    return TestClient(create_app(config=config))


def test_overview_returns_zeroed_payload_on_empty_state(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["cluster_counts"]["open"] == 0
    assert body["close_rate"] == 0.0
    assert body["regression_test_count"] == 0
    assert body["mttd_seconds"] is None
    assert body["mttr_seconds"] is None
    assert body["fix_pass_rate_30d"] is None
