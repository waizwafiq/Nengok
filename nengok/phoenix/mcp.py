"""
Phoenix MCP read-side client.

Speaks JSON-RPC 2.0 over stdio to the `@arizeai/phoenix-mcp` Node
package (spawned via `npx`). Used for read operations like listing
projects and annotation configs; writes still go through the Python
SDK in `client.py`.

Designed as an async context manager so subprocess lifecycle is tied
to a scoped block. A sync helper, ``run_preflight_check``, wraps the
async flow for callers that don't want to manage an event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Self

from nengok import __version__
from nengok.config import NengokConfig
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "nengok", "version": __version__}

_PROJECT_TOOL_HINTS = ("list-projects", "list_projects", "listprojects")
_ANNOTATION_TOOL_HINTS = (
    "list-annotation-configs",
    "list_annotation_configs",
    "get-annotation-configs",
    "get_annotation_configs",
    "listannotationconfigs",
)


class MCPError(RuntimeError):
    """Raised when the MCP subprocess returns an error or cannot be reached."""


class MCPUnavailableError(MCPError):
    """Raised when the MCP subprocess cannot be started (missing npx, etc)."""


@dataclass
class MCPProject:
    """Trimmed Phoenix project record returned by the MCP server."""

    name: str
    project_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class MCPAnnotationConfig:
    """Trimmed Phoenix annotation-config record."""

    name: str
    annotation_type: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


class PhoenixMCP:
    """
    Client for the ``@arizeai/phoenix-mcp`` Node subprocess.

    The MCP server speaks JSON-RPC 2.0 over stdio. This class owns
    the subprocess for the duration of a context-managed block,
    performs the MCP ``initialize`` handshake, and exposes typed
    wrappers around the read-only tools Nengok actually calls today.

        async with PhoenixMCP(config=config) as mcp:
            projects = await mcp.list_projects()
    """

    def __init__(self, config: NengokConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._tool_names: list[str] = []
        self._started = False

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        """Spawn the MCP subprocess and complete the initialize handshake."""
        if self._started:
            return
        if shutil.which(self._config.mcp_npx_command) is None:
            raise MCPUnavailableError(
                f"Cannot find '{self._config.mcp_npx_command}' on PATH. "
                "The Phoenix MCP integration needs Node.js (with npx). "
                "Install Node 18+ or disable MCP via NENGOK_MCP_ENABLED=0."
            )

        cmd = [self._config.mcp_npx_command, "-y", self._config.mcp_package]
        env = self._build_env()

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise MCPUnavailableError(
                f"Failed to launch '{cmd[0]}'. Install Node.js + npx, or "
                "disable MCP via NENGOK_MCP_ENABLED=0."
            ) from exc

        assert self._process.stdout is not None
        assert self._process.stderr is not None

        self._reader_task = asyncio.create_task(
            self._read_loop(self._process.stdout), name="phoenix-mcp-reader"
        )
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(self._process.stderr), name="phoenix-mcp-stderr"
        )

        try:
            await asyncio.wait_for(self._handshake(), timeout=self._config.mcp_startup_timeout)
        except (TimeoutError, MCPError):
            await self.close()
            raise

        self._started = True

    async def close(self) -> None:
        """Tear down the subprocess and cancel the reader tasks."""
        for waiter in self._pending.values():
            if not waiter.done():
                waiter.set_exception(MCPError("MCP subprocess closed before reply arrived."))
        self._pending.clear()

        process = self._process
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                    await process.wait()

        for task in (self._reader_task, self._stderr_task):
            if task is None or task.done():
                continue
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

        self._process = None
        self._reader_task = None
        self._stderr_task = None
        self._started = False

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any:
        """
        Invoke an MCP tool by exact name and return its parsed payload.

        Tool results from MCP are returned as a list of content blocks.
        For Phoenix tools the meaningful content is one text block whose
        body is JSON or whitespace-separated lines; this helper parses
        the JSON when it can and otherwise returns the raw text.
        """
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": dict(arguments or {})},
        )
        return _parse_tool_result(result)

    async def list_tools(self) -> list[str]:
        """Return the tool names the MCP server advertises."""
        if self._tool_names:
            return list(self._tool_names)
        result = await self._request("tools/list", {})
        tools = result.get("tools") or []
        self._tool_names = [str(tool.get("name")) for tool in tools if tool.get("name")]
        return list(self._tool_names)

    async def list_projects(self) -> list[MCPProject]:
        """List projects visible to the configured Phoenix base URL."""
        payload = await self._call_first_matching(_PROJECT_TOOL_HINTS)
        rows = _coerce_rows(payload)
        return [_to_project(row) for row in rows]

    async def get_annotation_configs(self) -> list[MCPAnnotationConfig]:
        """List annotation configs registered against the Phoenix instance."""
        payload = await self._call_first_matching(_ANNOTATION_TOOL_HINTS)
        rows = _coerce_rows(payload)
        return [_to_annotation_config(row) for row in rows]

    async def _call_first_matching(self, hints: Iterable[str]) -> Any:
        tool_name = await self._resolve_tool(hints)
        return await self.call_tool(tool_name)

    async def _resolve_tool(self, hints: Iterable[str]) -> str:
        available = await self.list_tools()
        if not available:
            raise MCPError("MCP server advertised no tools.")
        normalized = {name.lower().replace("_", "-"): name for name in available}
        for hint in hints:
            key = hint.lower().replace("_", "-")
            if key in normalized:
                return normalized[key]
        wanted = ", ".join(hints)
        raise MCPError(
            f"MCP server did not expose any of the expected tools: {wanted}. "
            f"Available: {', '.join(available)}."
        )

    async def _handshake(self) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        server_info = result.get("serverInfo") or {}
        logger.debug("MCP initialized: %s", server_info)
        await self._notify("notifications/initialized", {})

    async def _request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params),
        }
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send(message)
            response = await asyncio.wait_for(future, timeout=self._config.mcp_request_timeout)
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            err = response["error"] or {}
            raise MCPError(f"MCP error {err.get('code')}: {err.get('message', 'unknown')}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPError(f"MCP response missing result for {method}: {response!r}")
        return result

    async def _notify(self, method: str, params: Mapping[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    async def _send(self, message: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.stdin.is_closing():
            raise MCPError("MCP subprocess stdin is not available.")
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        process.stdin.write(encoded)
        await process.stdin.drain()

    async def _read_loop(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await stream.readline()
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception as exc:
                self._fail_pending(MCPError(f"MCP stdout read failed: {exc}"))
                return
            if not line:
                self._fail_pending(MCPError("MCP subprocess closed stdout."))
                return
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError:
                logger.debug("MCP non-JSON line: %s", stripped[:200])
                continue
            self._dispatch(message)

    def _dispatch(self, message: Mapping[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        request_id = message.get("id")
        if request_id is None:
            return
        future = self._pending.get(int(request_id))
        if future is None or future.done():
            return
        future.set_result(dict(message))

    def _fail_pending(self, error: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        while True:
            try:
                line = await stream.readline()
            except (asyncio.CancelledError, GeneratorExit):
                raise
            except Exception:
                return
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("MCP stderr: %s", text)

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PHOENIX_BASE_URL"] = self._config.phoenix_base_url
        if self._config.phoenix_api_key:
            env["PHOENIX_API_KEY"] = self._config.phoenix_api_key
        return env


@asynccontextmanager
async def open_mcp(config: NengokConfig) -> AsyncIterator[PhoenixMCP]:
    """Async context manager that starts and tears down a Phoenix MCP client."""
    client = PhoenixMCP(config=config)
    await client.start()
    try:
        yield client
    finally:
        await client.close()


def _parse_tool_result(result: Mapping[str, Any]) -> Any:
    content = result.get("content") or []
    if not isinstance(content, list) or not content:
        return result.get("structuredContent") or result
    chunks: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            chunks.append(block["text"])
    if not chunks:
        return result.get("structuredContent") or result
    joined = "\n".join(chunks).strip()
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


def _coerce_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "projects", "annotation_configs", "configs"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _to_project(row: Mapping[str, Any]) -> MCPProject:
    name = str(row.get("name") or row.get("project_name") or row.get("identifier") or "").strip()
    project_id = row.get("id") or row.get("project_id")
    return MCPProject(name=name, project_id=str(project_id) if project_id is not None else None, raw=row)


def _to_annotation_config(row: Mapping[str, Any]) -> MCPAnnotationConfig:
    name = str(row.get("name") or row.get("identifier") or "").strip()
    kind = row.get("annotation_type") or row.get("type") or row.get("kind")
    return MCPAnnotationConfig(
        name=name,
        annotation_type=str(kind) if kind is not None else None,
        raw=row,
    )
