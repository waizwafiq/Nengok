"""HTTP coverage for /api/v1/advice."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.server.main import create_app
from nengok.state.store import StateStore


def _setup(tmp_path: Path) -> tuple[StateStore, TestClient]:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    store = StateStore(config.state_db_path)
    return store, TestClient(create_app(config=config))


def test_list_and_activate_advice(tmp_path: Path) -> None:
    store, client = _setup(tmp_path)
    advice_id = store.record_clustering_advice(
        project="travel-planner-agent",
        prompt_amendment="Split flights and weather symptoms.",
        metrics_json=None,
    )

    listed = client.get("/api/v1/advice", params={"status": "proposed"}).json()
    assert [row["advice_id"] for row in listed] == [advice_id]

    activated = client.post(f"/api/v1/advice/{advice_id}/activate", json={"reviewer": "carol"}).json()
    assert activated["status"] == "active"
    assert activated["decided_by"] == "carol"

    assert store.get_active_advice("travel-planner-agent") is not None


def test_activate_unknown_advice_is_404(tmp_path: Path) -> None:
    _, client = _setup(tmp_path)
    response = client.post("/api/v1/advice/nope/activate", json={})
    assert response.status_code == 404
