"""HTTP coverage for the unauthenticated `/health` infrastructure probe."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nengok import __version__
from nengok.config import NengokConfig
from nengok.server.health import (
    DEFAULT_CACHE_TTL_SECONDS,
    HealthChecker,
    check_db_writable,
    check_gemini_reachable,
)
from nengok.server.main import create_app


def _make_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def _install_fake_checker(
    app: object,
    *,
    phoenix: bool,
    gemini: bool,
    db: bool,
) -> HealthChecker:
    """Replace the app's HealthChecker with one whose probes are pre-canned."""
    checker = HealthChecker(
        phoenix_check=lambda _config: phoenix,
        gemini_check=lambda _config: gemini,
        db_check=lambda _config: db,
    )
    app.state.health_checker = checker
    return checker


def test_health_endpoint_returns_expected_payload_shape(tmp_path: Path) -> None:
    app = create_app(config=_make_config(tmp_path))
    _install_fake_checker(app, phoenix=True, gemini=True, db=True)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "ok",
        "version": __version__,
        "phoenix_reachable": True,
        "gemini_reachable": True,
        "db_writable": True,
        "triage_adk_ratio": payload["triage_adk_ratio"],
    }
    assert payload["triage_adk_ratio"] is None or 0.0 <= payload["triage_adk_ratio"] <= 1.0


def test_health_endpoint_requires_no_auth_even_when_token_set(tmp_path: Path) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        dashboard_auth_token="s3cret",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    app = create_app(config=config)
    _install_fake_checker(app, phoenix=True, gemini=True, db=True)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_endpoint_reports_each_dependency_individually(tmp_path: Path) -> None:
    app = create_app(config=_make_config(tmp_path))
    _install_fake_checker(app, phoenix=True, gemini=False, db=True)
    client = TestClient(app)

    payload = client.get("/health").json()

    assert payload["phoenix_reachable"] is True
    assert payload["gemini_reachable"] is False
    assert payload["db_writable"] is True


def test_health_endpoint_is_exempt_from_rate_limit(tmp_path: Path) -> None:
    app = create_app(config=_make_config(tmp_path))
    _install_fake_checker(app, phoenix=True, gemini=True, db=True)
    client = TestClient(app, client=("203.0.113.5", 50000))

    for _ in range(70):
        response = client.get("/health")
        assert response.status_code == 200


class _ManualClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_reachability_results_are_cached_within_ttl() -> None:
    config = _make_config(Path("/tmp"))
    phoenix_calls = {"count": 0}
    gemini_calls = {"count": 0}

    def phoenix(_config: NengokConfig) -> bool:
        phoenix_calls["count"] += 1
        return True

    def gemini(_config: NengokConfig) -> bool:
        gemini_calls["count"] += 1
        return True

    clock = _ManualClock()
    checker = HealthChecker(
        phoenix_check=phoenix,
        gemini_check=gemini,
        db_check=lambda _c: True,
        clock=clock,
    )

    for _ in range(20):
        checker.snapshot(config)

    assert phoenix_calls["count"] == 1
    assert gemini_calls["count"] == 1


def test_cached_results_refresh_after_ttl_expires() -> None:
    config = _make_config(Path("/tmp"))
    phoenix_calls = {"count": 0}

    def phoenix(_config: NengokConfig) -> bool:
        phoenix_calls["count"] += 1
        return True

    clock = _ManualClock()
    checker = HealthChecker(
        phoenix_check=phoenix,
        gemini_check=lambda _c: True,
        db_check=lambda _c: True,
        clock=clock,
    )

    checker.snapshot(config)
    clock.now += DEFAULT_CACHE_TTL_SECONDS + 0.01
    checker.snapshot(config)

    assert phoenix_calls["count"] == 2


def _isolate_google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "GOOGLE_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(key, raising=False)


def test_check_gemini_reachable_vertex_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("google.genai", reason="stubs google.genai.Client")
    _isolate_google_env(monkeypatch)

    class _StubClient:
        def __init__(self, **_kwargs: object) -> None:
            self.models = self

        def generate_content(self, **_kwargs: object) -> object:
            return type("_R", (), {"text": "ok", "usage_metadata": None})()

    monkeypatch.setattr("google.genai.Client", _StubClient, raising=False)
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        gemini_use_vertex=True,
        vertex_project="proj",
        state_db_path=tmp_path / "state.db",
    )

    assert check_gemini_reachable(config) is True


def test_check_gemini_reachable_vertex_missing_project_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_google_env(monkeypatch)
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        gemini_use_vertex=True,
        vertex_project=None,
        state_db_path=tmp_path / "state.db",
    )

    # Factory raises MissingApiKeyError (no project); the probe swallows it.
    assert check_gemini_reachable(config) is False


def test_check_gemini_reachable_ai_studio_without_key_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_google_env(monkeypatch)
    config = NengokConfig(
        phoenix_base_url="http://localhost:6006",
        gemini_use_vertex=False,
        google_api_key=None,
        state_db_path=tmp_path / "state.db",
    )

    assert check_gemini_reachable(config) is False


def test_db_writable_probe_returns_true_for_writable_path(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    assert check_db_writable(config) is True


def test_db_writable_probe_returns_false_when_parent_blocked(tmp_path: Path) -> None:
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("file in the way")
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=blocked / "state.db",
    )

    assert check_db_writable(config) is False


def test_db_writable_probe_returns_false_when_db_corrupt(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    db_path.write_bytes(b"not a sqlite database")
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=db_path,
    )

    with pytest.raises(sqlite3.DatabaseError):
        with sqlite3.connect(db_path) as conn:
            conn.execute("SELECT 1 FROM sqlite_master").fetchone()

    assert check_db_writable(config) is False
