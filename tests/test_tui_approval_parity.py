"""
Approval-row parity between the browser dashboard and the TUI.

A decision submitted via the TUI API client must land in
`nengok_approvals` with the same payload as one submitted via the
dashboard route, differing only on the `source` discriminator. This
test stands up the FastAPI server in a thread, drives both surfaces
against it, and asserts the rows match.
"""

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

pytest.importorskip("textual", reason="The `tui` extra is required for the parity test.")

from nengok.tui.api_client import APPROVAL_SOURCE_TUI, TuiApiClient


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
            description="parity-test cluster",
            status=ClusterStatus.DIAGNOSED,
            member_span_ids=["span-a"],
            exemplar_span_ids=[],
            created_at=now,
            updated_at=now,
        )
    )


@contextmanager
def _running_server(config: NengokConfig) -> Iterator[str]:
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


def test_tui_and_dashboard_record_identical_rows_except_source(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-parity-dashboard")
    _seed_cluster(store, "c-parity-tui")

    async def _drive() -> tuple[dict, dict]:
        with _running_server(config) as base_url:
            client = TuiApiClient(base_url=base_url, auth_token=None)
            tui_payload = await client.submit_approval(
                cluster_id="c-parity-tui",
                decision="approved",
                reviewer="alice",
                reason="ssh approval",
                source=APPROVAL_SOURCE_TUI,
            )
            async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
                response = await http.post(
                    "/api/v1/clusters/c-parity-dashboard/approvals",
                    json={
                        "decision": "approved",
                        "reviewer": "alice",
                        "reason": "ssh approval",
                    },
                )
                response.raise_for_status()
                dashboard_payload = response.json()
        return tui_payload, dashboard_payload

    tui_resp, dashboard_resp = asyncio.run(_drive())
    assert tui_resp["source"] == "tui"
    assert dashboard_resp["source"] == "dashboard"

    tui_row = store.list_cluster_approvals("c-parity-tui")[0]
    dashboard_row = store.list_cluster_approvals("c-parity-dashboard")[0]

    for field in ("decision", "reviewer", "reason"):
        assert tui_row[field] == dashboard_row[field], field
    assert tui_row["source"] == "tui"
    assert dashboard_row["source"] == "dashboard"
    assert {key for key in tui_row} == {key for key in dashboard_row}


def test_legacy_post_defaults_source_to_api(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-parity-legacy")

    async def _drive() -> None:
        with _running_server(config) as base_url:
            async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
                response = await http.post(
                    "/api/v1/approvals",
                    json={
                        "cluster_id": "c-parity-legacy",
                        "decision": "approved",
                        "decided_by": "alice",
                        "notes": "imported via script",
                    },
                )
                response.raise_for_status()

    asyncio.run(_drive())

    row = store.list_cluster_approvals("c-parity-legacy")[0]
    assert row["source"] == "api"
