"""
Phoenix MCP integration scaffold.

MCP is used for *read* operations — listing projects, retrieving
sessions, sampling annotation configs — while the Python SDK in
`client.py` handles *writes* (datasets, experiments, prompts).

The current scaffold is a no-op placeholder: in the implementation
pass it will speak to `@arizeai/phoenix-mcp` via the Google ADK
tool-calling interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nengok.config import NengokConfig


@dataclass
class PhoenixMCP:
    config: NengokConfig

    async def list_projects(self) -> list[str]:
        raise NotImplementedError("MCP wiring is implemented in the integration pass.")

    async def list_traces(self, *, project: str, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_sessions(self, *, project: str, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_annotation_configs(self, *, project: str) -> list[dict[str, Any]]:
        raise NotImplementedError
