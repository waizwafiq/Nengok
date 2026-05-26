"""HTTP coverage for the dashboard bearer-token guard and CORS wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient

from nengok.cli import _enforce_dashboard_safety
from nengok.config import NengokConfig
from nengok.server.main import create_app


def _make_config(
    tmp_path: Path,
    *,
    dashboard_auth_token: str | None = None,
    dashboard_cors_origins: list[str] | None = None,
) -> NengokConfig:
    overrides: dict[str, object] = {
        "config_path": tmp_path / "missing.toml",
        "phoenix_base_url": "http://localhost:6006",
        "google_api_key": "AIzaTEST",
        "artifacts_dir": tmp_path / "artifacts",
        "state_db_path": tmp_path / "state.db",
    }
    if dashboard_auth_token is not None:
        overrides["dashboard_auth_token"] = dashboard_auth_token
    if dashboard_cors_origins is not None:
        overrides["dashboard_cors_origins"] = dashboard_cors_origins
    return NengokConfig.load(**overrides)


def test_api_returns_200_when_no_token_configured(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    client = TestClient(create_app(config=config))

    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 200


def test_api_returns_401_when_token_set_and_header_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")
    client = TestClient(create_app(config=config))

    response = client.get("/api/v1/dashboard/overview")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_api_returns_401_when_token_set_and_header_wrong(tmp_path: Path) -> None:
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")
    client = TestClient(create_app(config=config))

    response = client.get(
        "/api/v1/dashboard/overview",
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401


def test_api_returns_200_when_token_set_and_header_matches(tmp_path: Path) -> None:
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")
    client = TestClient(create_app(config=config))

    response = client.get(
        "/api/v1/dashboard/overview",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert response.status_code == 200


def test_health_route_is_token_gated_when_configured(tmp_path: Path) -> None:
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")
    client = TestClient(create_app(config=config))

    assert client.get("/api/v1/health").status_code == 401
    response = client.get("/api/v1/health", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200


def test_cors_preflight_allows_configured_origin(tmp_path: Path) -> None:
    config = _make_config(
        tmp_path,
        dashboard_cors_origins=["https://nengok.example.com"],
    )
    client = TestClient(create_app(config=config))

    response = client.options(
        "/api/v1/dashboard/overview",
        headers={
            "Origin": "https://nengok.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://nengok.example.com"


def test_cors_preflight_rejects_unlisted_origin(tmp_path: Path) -> None:
    config = _make_config(
        tmp_path,
        dashboard_cors_origins=["https://nengok.example.com"],
    )
    client = TestClient(create_app(config=config))

    response = client.options(
        "/api/v1/dashboard/overview",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


def test_production_refuses_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NENGOK_PRODUCTION", "true")
    config = _make_config(tmp_path)

    with pytest.raises(typer.Exit) as exc:
        _enforce_dashboard_safety(config=config, bind_host="0.0.0.0")

    assert exc.value.exit_code == 2
    err = capsys.readouterr().err
    assert "dashboard_auth_token is unset" in err


def test_production_refuses_when_bound_localhost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NENGOK_PRODUCTION", "true")
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")

    with pytest.raises(typer.Exit) as exc:
        _enforce_dashboard_safety(config=config, bind_host="127.0.0.1")

    assert exc.value.exit_code == 2
    err = capsys.readouterr().err
    assert "localhost-only" in err


def test_production_accepts_token_and_external_bind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NENGOK_PRODUCTION", "true")
    config = _make_config(tmp_path, dashboard_auth_token="s3cret")

    _enforce_dashboard_safety(config=config, bind_host="0.0.0.0")


def test_non_local_bind_prints_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NENGOK_PRODUCTION", raising=False)
    config = _make_config(tmp_path)

    _enforce_dashboard_safety(config=config, bind_host="192.168.1.10")

    err = capsys.readouterr().err
    assert "192.168.1.10" in err
    assert "dashboard_auth_token" in err
