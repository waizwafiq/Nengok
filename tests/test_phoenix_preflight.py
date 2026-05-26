"""Tests for the MCP preflight check wired into `nengok run`."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from nengok.config import NengokConfig
from nengok.phoenix import mcp as mcp_module
from nengok.phoenix.preflight import (
    PreflightOutcome,
    run_preflight,
)


def _make_config(tmp_path: Path, *, project: str, mcp_enabled: bool = True) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key="AIzaTEST",
        project_identifier=project,
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
        mcp_enabled=mcp_enabled,
        mcp_startup_timeout=2.0,
        mcp_request_timeout=2.0,
    )


class _FakeStdin:
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue
        self._closed = False
        self._buffer = bytearray()

    def write(self, data: bytes) -> None:
        self._buffer.extend(data)
        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            self._queue.put_nowait(bytes(line).strip())

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self._closed = True

    def is_closing(self) -> bool:
        return self._closed


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.stdin = _FakeStdin(self.stdin_queue)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.returncode: int | None = None
        self._wait_event = asyncio.Event()

    def terminate(self) -> None:
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self._wait_event.set()

    def kill(self) -> None:
        self.terminate()

    async def wait(self) -> int:
        await self._wait_event.wait()
        return self.returncode or 0


Handler = Callable[[Mapping[str, Any]], Mapping[str, Any] | None]


class _FakeMCPServer:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.process: _FakeProcess | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> _FakeProcess:
        if self.process is None:
            self.process = _FakeProcess()
            self._task = asyncio.create_task(self._run(self.process))
        return self.process

    async def _run(self, process: _FakeProcess) -> None:
        try:
            while True:
                line = await process.stdin_queue.get()
                if not line:
                    continue
                message = json.loads(line.decode("utf-8"))
                response = self.handler(message)
                if response is not None:
                    encoded = (json.dumps(response) + "\n").encode("utf-8")
                    process.stdout.feed_data(encoded)
        except asyncio.CancelledError:
            raise


def _install_fake_subprocess(monkeypatch: pytest.MonkeyPatch, server: _FakeMCPServer) -> None:
    async def fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        return server.start()

    monkeypatch.setattr(mcp_module.shutil, "which", lambda _name: "npx")
    monkeypatch.setattr(mcp_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


def _ok(request_id: int, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _tool_text(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _projects_handler(project_names: list[str]) -> Handler:
    def handler(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        assert isinstance(request_id, int)
        if method == "initialize":
            return _ok(request_id, {"serverInfo": {}})
        if method == "tools/list":
            return _ok(
                request_id,
                {"tools": [{"name": "list-projects"}, {"name": "list-annotation-configs"}]},
            )
        if method == "tools/call":
            params = message.get("params") or {}
            tool_name = params.get("name")
            if tool_name == "list-projects":
                payload = [{"name": name, "id": f"id-{name}"} for name in project_names]
                return _ok(request_id, _tool_text(payload))
            if tool_name == "list-annotation-configs":
                payload = [{"name": "hallucination", "type": "CATEGORICAL"}]
                return _ok(request_id, _tool_text(payload))
        raise AssertionError(f"unexpected call: {message!r}")

    return handler


def test_preflight_skipped_when_mcp_disabled(tmp_path: Path) -> None:
    config = _make_config(tmp_path, project="travel-planner-agent", mcp_enabled=False)
    echoed: list[str] = []
    result = run_preflight(config, echo=echoed.append)

    assert result.outcome is PreflightOutcome.SKIPPED
    assert echoed == []


def test_preflight_unavailable_when_npx_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_module.shutil, "which", lambda _name: None)
    config = _make_config(tmp_path, project="travel-planner-agent")
    echoed: list[str] = []
    result = run_preflight(config, echo=echoed.append)

    assert result.outcome is PreflightOutcome.MCP_UNAVAILABLE
    assert echoed == []


def test_preflight_ok_when_project_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = _FakeMCPServer(_projects_handler(["travel-planner-agent", "default"]))
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path, project="travel-planner-agent")

    echoed: list[str] = []
    try:
        result = run_preflight(config, echo=echoed.append)
    finally:
        if server.process is not None:
            _ensure_terminated(server.process)

    assert result.outcome is PreflightOutcome.OK
    assert result.known_projects == ("travel-planner-agent", "default")
    assert result.annotation_config_count == 1
    assert echoed == []


def test_preflight_warns_when_project_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server = _FakeMCPServer(_projects_handler(["default"]))
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path, project="travel-planner-agent")

    echoed: list[str] = []
    try:
        result = run_preflight(config, echo=echoed.append)
    finally:
        if server.process is not None:
            _ensure_terminated(server.process)

    assert result.outcome is PreflightOutcome.PROJECT_MISSING
    assert "travel-planner-agent" in result.message
    assert echoed and "travel-planner-agent" in echoed[0]


def _ensure_terminated(process: _FakeProcess) -> None:
    with contextlib.suppress(Exception):
        process.terminate()
