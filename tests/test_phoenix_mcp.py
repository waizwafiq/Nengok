"""Unit tests for the Phoenix MCP subprocess client."""

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
from nengok.phoenix.mcp import (
    MCPAnnotationConfig,
    MCPError,
    MCPProject,
    MCPUnavailableError,
    PhoenixMCP,
    _coerce_rows,
    _parse_tool_result,
)


def _make_config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
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
        self.process = _FakeProcess()
        self.handler = handler
        self.requests: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                line = await self.process.stdin_queue.get()
                if not line:
                    continue
                message = json.loads(line.decode("utf-8"))
                self.requests.append(message)
                response = self.handler(message)
                if response is not None:
                    encoded = (json.dumps(response) + "\n").encode("utf-8")
                    self.process.stdout.feed_data(encoded)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def _install_fake_subprocess(monkeypatch: pytest.MonkeyPatch, server: _FakeMCPServer) -> None:
    async def fake_create_subprocess_exec(*_args: Any, **_kwargs: Any) -> _FakeProcess:
        server.start()
        return server.process

    monkeypatch.setattr(mcp_module.shutil, "which", lambda _name: "npx")
    monkeypatch.setattr(mcp_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


def _tool_text_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _ok(request_id: int, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _err(request_id: int, message: str, code: int = -32000) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def test_parse_tool_result_handles_json_text() -> None:
    result = {"content": [{"type": "text", "text": json.dumps({"projects": [{"name": "alpha"}]})}]}
    parsed = _parse_tool_result(result)
    assert parsed == {"projects": [{"name": "alpha"}]}


def test_parse_tool_result_falls_back_to_raw_text() -> None:
    result = {"content": [{"type": "text", "text": "not-json"}]}
    assert _parse_tool_result(result) == "not-json"


def test_parse_tool_result_prefers_structured_content_when_no_text() -> None:
    structured = {"projects": []}
    result = {"content": [], "structuredContent": structured}
    assert _parse_tool_result(result) is structured


def test_coerce_rows_unwraps_known_keys() -> None:
    assert _coerce_rows([{"a": 1}]) == [{"a": 1}]
    assert _coerce_rows({"data": [{"a": 1}]}) == [{"a": 1}]
    assert _coerce_rows({"projects": [{"a": 1}]}) == [{"a": 1}]
    assert _coerce_rows({"annotation_configs": [{"a": 1}]}) == [{"a": 1}]
    assert _coerce_rows("garbage") == []


@pytest.mark.asyncio
async def test_start_raises_when_npx_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_module.shutil, "which", lambda _name: None)
    config = _make_config(tmp_path)
    client = PhoenixMCP(config=config)
    with pytest.raises(MCPUnavailableError):
        await client.start()


@pytest.mark.asyncio
async def test_list_projects_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        assert isinstance(request_id, int)
        if method == "initialize":
            return _ok(request_id, {"serverInfo": {"name": "fake-mcp"}})
        if method == "tools/list":
            return _ok(
                request_id,
                {"tools": [{"name": "list-projects"}, {"name": "list-annotation-configs"}]},
            )
        if method == "tools/call":
            params = message.get("params") or {}
            if params.get("name") == "list-projects":
                payload = [
                    {"name": "travel-planner-agent", "id": "p1"},
                    {"name": "default", "id": "p2"},
                ]
                return _ok(request_id, _tool_text_result(payload))
        raise AssertionError(f"unexpected call: {message!r}")

    server = _FakeMCPServer(handler)
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path)

    try:
        async with PhoenixMCP(config=config) as client:
            projects = await client.list_projects()
    finally:
        await server.stop()

    assert [p.name for p in projects] == ["travel-planner-agent", "default"]
    assert all(isinstance(p, MCPProject) for p in projects)
    assert projects[0].project_id == "p1"


@pytest.mark.asyncio
async def test_list_annotation_configs_unwraps_data_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        assert isinstance(request_id, int)
        if method == "initialize":
            return _ok(request_id, {"serverInfo": {}})
        if method == "tools/list":
            return _ok(request_id, {"tools": [{"name": "list-annotation-configs"}]})
        if method == "tools/call":
            payload = {
                "data": [
                    {"name": "hallucination", "annotation_type": "CATEGORICAL"},
                    {"name": "latency", "type": "CONTINUOUS"},
                ],
            }
            return _ok(request_id, _tool_text_result(payload))
        raise AssertionError(f"unexpected call: {message!r}")

    server = _FakeMCPServer(handler)
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path)

    try:
        async with PhoenixMCP(config=config) as client:
            configs = await client.get_annotation_configs()
    finally:
        await server.stop()

    assert [c.name for c in configs] == ["hallucination", "latency"]
    assert configs[0].annotation_type == "CATEGORICAL"
    assert isinstance(configs[1], MCPAnnotationConfig)


@pytest.mark.asyncio
async def test_call_tool_error_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        assert isinstance(request_id, int)
        if method == "initialize":
            return _ok(request_id, {})
        return _err(request_id, "tool exploded")

    server = _FakeMCPServer(handler)
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path)

    try:
        async with PhoenixMCP(config=config) as client:
            with pytest.raises(MCPError, match="tool exploded"):
                await client.list_tools()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_missing_tool_raises_with_available_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(message: Mapping[str, Any]) -> Mapping[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            return None
        assert isinstance(request_id, int)
        if method == "initialize":
            return _ok(request_id, {})
        if method == "tools/list":
            return _ok(request_id, {"tools": [{"name": "create-prompt"}]})
        raise AssertionError(f"unexpected call: {message!r}")

    server = _FakeMCPServer(handler)
    _install_fake_subprocess(monkeypatch, server)
    config = _make_config(tmp_path)

    try:
        async with PhoenixMCP(config=config) as client:
            with pytest.raises(MCPError, match="did not expose"):
                await client.list_projects()
    finally:
        await server.stop()
