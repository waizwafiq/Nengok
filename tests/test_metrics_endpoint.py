"""Prometheus /metrics endpoint exposes Nengok counters when enabled."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.server.main import create_app


@pytest.fixture
def base_config(tmp_config: NengokConfig) -> NengokConfig:
    return tmp_config


def test_metrics_endpoint_disabled_by_default(base_config: NengokConfig) -> None:
    app = create_app(config=base_config)
    client = TestClient(app)

    response = client.get("/metrics")

    assert "nengok_cycles_total" not in response.text


def test_metrics_endpoint_returns_prometheus_text(base_config: NengokConfig) -> None:
    from nengok.server import metrics as nengok_metrics

    nengok_metrics.cycles_total.labels(status="ok").inc()
    nengok_metrics.gemini_tokens_total.labels(stage="fixer").inc(150)

    config = replace(base_config, metrics_enabled=True)
    app = create_app(config=config)
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "nengok_cycles_total" in body
    assert "nengok_gemini_tokens_total" in body


def test_metrics_enabled_via_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.setenv("PHOENIX_BASE_URL", "http://localhost:6006")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaTEST")
    monkeypatch.setenv("NENGOK_METRICS_ENABLED", "true")

    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )

    assert config.metrics_enabled is True
    client = TestClient(create_app(config=config))
    assert client.get("/metrics").status_code == 200
