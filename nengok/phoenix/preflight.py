"""
Pre-cycle MCP sanity check.

Runs before the Observer fires to catch the easiest class of
operator errors: pointing Nengok at a Phoenix project that does
not exist yet. The check is best-effort. If the MCP subprocess
is unavailable for any reason, the warning is silently dropped
so the actual cycle still runs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from nengok.config import NengokConfig
from nengok.phoenix.mcp import (
    MCPError,
    MCPUnavailableError,
    PhoenixMCP,
)
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

Echo = Callable[[str], None]


class PreflightOutcome(str, Enum):
    OK = "ok"
    PROJECT_MISSING = "project_missing"
    MCP_UNAVAILABLE = "mcp_unavailable"
    MCP_ERROR = "mcp_error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PreflightResult:
    outcome: PreflightOutcome
    message: str
    known_projects: tuple[str, ...] = ()
    annotation_config_count: int = 0


def run_preflight(config: NengokConfig, *, echo: Echo | None = None) -> PreflightResult:
    """
    Run the MCP preflight check synchronously.

    Returns a :class:`PreflightResult` so callers (the CLI, tests)
    can react without parsing log output. When ``echo`` is supplied,
    a one-line operator-facing message is emitted only when the
    outcome is worth surfacing (project missing or hard MCP error).
    Connector-availability issues are kept to the debug log because
    MCP is optional in v0.1.
    """
    if not config.mcp_enabled:
        result = PreflightResult(
            outcome=PreflightOutcome.SKIPPED,
            message="MCP preflight skipped (NENGOK_MCP_ENABLED=0).",
        )
        logger.debug(result.message)
        return result

    try:
        result = asyncio.run(_preflight_async(config))
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" in str(exc):
            result = _run_in_thread(config)
        else:
            raise

    if echo is not None and result.outcome in {
        PreflightOutcome.PROJECT_MISSING,
        PreflightOutcome.MCP_ERROR,
    }:
        echo(result.message)
    return result


async def _preflight_async(config: NengokConfig) -> PreflightResult:
    try:
        async with PhoenixMCP(config=config) as mcp:
            projects = await mcp.list_projects()
            try:
                annotation_configs = await mcp.get_annotation_configs()
            except MCPError as exc:
                logger.debug("MCP annotation-config lookup failed: %s", exc)
                annotation_configs = []
    except MCPUnavailableError as exc:
        message = f"MCP preflight skipped: {exc}"
        logger.debug(message)
        return PreflightResult(outcome=PreflightOutcome.MCP_UNAVAILABLE, message=message)
    except MCPError as exc:
        message = f"MCP preflight failed: {exc}"
        logger.warning(message)
        return PreflightResult(outcome=PreflightOutcome.MCP_ERROR, message=message)

    names = tuple(p.name for p in projects if p.name)
    annotation_count = len(annotation_configs)
    target = config.project_identifier

    if target in names:
        message = f"Phoenix project '{target}' is visible to MCP (annotation configs: {annotation_count})."
        logger.info(message)
        return PreflightResult(
            outcome=PreflightOutcome.OK,
            message=message,
            known_projects=names,
            annotation_config_count=annotation_count,
        )

    hint = ", ".join(sorted(names)) or "(none)"
    message = (
        f"Heads up: Phoenix project '{target}' was not found via MCP. "
        f"Known projects: {hint}. The cycle will still run, but the Observer "
        "will likely return zero spans."
    )
    logger.warning(message)
    return PreflightResult(
        outcome=PreflightOutcome.PROJECT_MISSING,
        message=message,
        known_projects=names,
        annotation_config_count=annotation_count,
    )


def _run_in_thread(config: NengokConfig) -> PreflightResult:
    import threading

    result_box: list[PreflightResult] = []
    error_box: list[BaseException] = []

    def runner() -> None:
        try:
            result_box.append(asyncio.run(_preflight_async(config)))
        except BaseException as exc:
            error_box.append(exc)

    thread = threading.Thread(target=runner, name="nengok-mcp-preflight", daemon=True)
    thread.start()
    thread.join()

    if error_box:
        raise error_box[0]
    return result_box[0]
