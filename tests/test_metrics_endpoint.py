"""Prometheus /metrics endpoint exposes Nengok counters when enabled."""

from __future__ import annotations

from dataclasses import replace

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
