"""HTTP coverage for the dashboard per-IP rate limiter."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nengok.config import NengokConfig
from nengok.server.main import create_app
from nengok.server.rate_limit import DEFAULT_RATE_LIMIT


def _make_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def _client_from(app: FastAPI, host: str) -> TestClient:
    return TestClient(app, client=(host, 50000))


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(config=_make_config(tmp_path))


@pytest.fixture
def remote_client(app: FastAPI) -> TestClient:
    return _client_from(app, "203.0.113.5")


@pytest.fixture
def loopback_client(app: FastAPI) -> TestClient:
    return _client_from(app, "127.0.0.1")


def test_remote_ip_is_throttled_after_sixty_requests(remote_client: TestClient) -> None:
    for _ in range(60):
        assert remote_client.get("/api/v1/dashboard/overview").status_code == 200

    response = remote_client.get("/api/v1/dashboard/overview")
    assert response.status_code == 429


def test_throttled_response_is_json_with_retry_after(remote_client: TestClient) -> None:
    for _ in range(60):
        remote_client.get("/api/v1/dashboard/overview")

    response = remote_client.get("/api/v1/dashboard/overview")
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers.get("retry-after") == "60"

    body = response.json()
    assert body["error"] == "rate_limit_exceeded"
    assert "60" in body["limit"]
    assert "minute" in body["limit"]


def test_loopback_ipv4_is_exempt(loopback_client: TestClient) -> None:
    for _ in range(120):
        response = loopback_client.get("/api/v1/dashboard/overview")
        assert response.status_code == 200, "127.0.0.1 must never be throttled"


def test_loopback_ipv6_is_exempt(app: FastAPI) -> None:
    client = _client_from(app, "::1")
    for _ in range(120):
        assert client.get("/api/v1/dashboard/overview").status_code == 200


def test_separate_ips_have_separate_buckets(app: FastAPI) -> None:
    first = _client_from(app, "198.51.100.7")
    for _ in range(60):
        first.get("/api/v1/dashboard/overview")
    assert first.get("/api/v1/dashboard/overview").status_code == 429

    second = _client_from(app, "203.0.113.42")
    assert second.get("/api/v1/dashboard/overview").status_code == 200


def test_default_limit_is_sixty_per_minute() -> None:
    assert DEFAULT_RATE_LIMIT == "60/minute"
