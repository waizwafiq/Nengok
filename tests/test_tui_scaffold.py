"""Smoke coverage for the `nengok review` scaffold and its API client."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nengok.cli import app as cli_app
from nengok.config import NengokConfig
from nengok.server.main import create_app

textual = pytest.importorskip("textual", reason="The `tui` extra is required for the TUI scaffold tests.")


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def test_api_client_targets_health_route(tmp_path: Path) -> None:
    from nengok.tui.api_client import TuiApiClient

    config = _config(tmp_path)
    fastapi_app = create_app(config=config)
    with TestClient(fastapi_app) as fastapi_client:
        base_url = str(fastapi_client.base_url)
        token = config.dashboard_auth_token
        client = TuiApiClient(base_url=base_url, auth_token=token)

        async def call() -> dict:
            return await client.ping()

        payload = asyncio.run(_run_with_fake_transport(call, fastapi_app))

    assert payload["status"] == "ok"


def test_review_command_aborts_when_server_unreachable(tmp_path: Path) -> None:
    runner = CliRunner()
    monkey_state = tmp_path / "state.db"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    env = {
        "NENGOK_STATE_DB_PATH": str(monkey_state),
        "NENGOK_ARTIFACTS_DIR": str(artifacts),
        "PHOENIX_BASE_URL": "http://localhost:6006",
        "GOOGLE_API_KEY": "AIzaTEST",
        "NENGOK_PROJECT": "travel-planner-agent",
    }
    result = runner.invoke(
        cli_app,
        ["review", "--host", "127.0.0.1", "--port", "1"],
        env=env,
    )

    assert result.exit_code == 1
    assert "phoenix-unreachable" in result.output


async def _run_with_fake_transport(call, fastapi_app):
    """Patch the API client to drive the FastAPI app in-process via httpx.ASGITransport."""
    import httpx

    from nengok.tui.api_client import TuiApiClient

    async def _patched_client(self):
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=self._headers,
            timeout=self._timeout_seconds,
        ) as client:
            yield client

    original = TuiApiClient._client
    from contextlib import asynccontextmanager

    TuiApiClient._client = asynccontextmanager(_patched_client)
    try:
        return await call()
    finally:
        TuiApiClient._client = original
