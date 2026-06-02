"""Headless Pilot smoke tests for the cluster list, detail, and approval screens."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import uvicorn

from nengok.config import NengokConfig
from nengok.core.types import Cluster, ClusterStatus
from nengok.server.main import create_app
from nengok.state.store import StateStore

pytest.importorskip("textual", reason="The `tui` extra is required for the TUI screen tests.")

from nengok.tui.api_client import TuiApiClient
from nengok.tui.app import NengokReviewApp


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
            name=f"cluster {cluster_id}",
            description="seeded for the TUI Pilot test",
            status=ClusterStatus.DIAGNOSED,
            member_span_ids=["span-a", "span-b"],
            exemplar_span_ids=[],
            created_at=now,
            updated_at=now,
        )
    )


@contextmanager
def _running_server(config: NengokConfig) -> Iterator[str]:
    """Run uvicorn in a thread and yield the base URL once /health responds."""
    fastapi_app = create_app(config=config)
    server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            lifespan="on",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        port = _wait_for_port(server)
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _wait_for_port(server: uvicorn.Server, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        servers = getattr(server, "servers", None)
        if servers:
            sockets = getattr(servers[0], "sockets", None) or ()
            if sockets:
                return int(sockets[0].getsockname()[1])
        time.sleep(0.05)
    raise RuntimeError("uvicorn server did not bind a socket in time")


def _wait_for_health(base_url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"FastAPI server at {base_url} never reported healthy")


def test_cluster_list_renders_seeded_clusters(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-tui-1")
    _seed_cluster(store, "c-tui-2")

    async def _drive() -> int:
        with _running_server(config) as base_url:
            client = TuiApiClient(base_url=base_url, auth_token=None)
            app = NengokReviewApp(api_client=client)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                from nengok.tui.screens.cluster_list import ClusterListScreen

                screen = app.screen
                assert isinstance(screen, ClusterListScreen)
                return len(screen._cluster_ids)

    rendered = asyncio.run(_drive())
    assert rendered == 2


def test_detail_screen_loads_and_returns_to_list(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-tui-detail")

    async def _drive() -> str:
        with _running_server(config) as base_url:
            client = TuiApiClient(base_url=base_url, auth_token=None)
            app = NengokReviewApp(api_client=client)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                from nengok.tui.screens.cluster_detail import ClusterDetailScreen

                screen = app.screen
                assert isinstance(screen, ClusterDetailScreen)
                cluster_id = screen.cluster_id
                await pilot.press("escape")
                await pilot.pause()
                return cluster_id

    cluster_id = asyncio.run(_drive())
    assert cluster_id == "c-tui-detail"


def test_approval_modal_records_decision(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-tui-approve")

    async def _drive() -> list[dict]:
        with _running_server(config) as base_url:
            client = TuiApiClient(base_url=base_url, auth_token=None)
            app = NengokReviewApp(api_client=client)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
                await pilot.press("a")
                await pilot.pause()
                await pilot.pause()
                await pilot.press("enter")
                await pilot.pause()
                await pilot.pause()
        return store.list_cluster_approvals("c-tui-approve")

    rows = asyncio.run(_drive())
    assert len(rows) == 1
    assert rows[0]["decision"] == "approved"
