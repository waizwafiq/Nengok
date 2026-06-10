"""
ADK triage agent that gates every Nengok cycle.

An ``LlmAgent`` from the Google Agent Development Kit, armed with an
``MCPToolset`` pointed at the pinned ``@arizeai/phoenix-mcp`` package,
inspects recent Phoenix traffic and returns a :class:`TriageVerdict`
that tells the orchestrator whether the deterministic pipeline should
wake. The Diagnoser, Fixer, and Verifier stay deterministic on purpose;
this module is the single ADK surface in the loop.

Every ``google.adk`` import below is verified against the exact
``google-adk==2.2.0`` pin in ``pyproject.toml``. The MCPToolset module
path has moved between ADK releases, so bumping the pin means
re-verifying these imports against that version's reference docs.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nengok.config import NengokConfig
from nengok.errors import OptionalDependencyError, TriageError
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

TRIAGE_PROMPT_PATH = Path(__file__).parent / "triage_prompt.md"
TRIAGE_APP_NAME = "nengok-triage"
TRIAGE_USER_ID = "nengok-orchestrator"
TRIAGE_AGENT_NAME = "nengok_triage"

ADK_INSTALL_HINT = 'pip install "nengok[adk]"'

RunnerFactory = Callable[[NengokConfig], Any]


class TriageVerdict(BaseModel):
    """
    Structured decision the triage agent returns per cycle.

    ``extra='forbid'`` so an out-of-schema field from the LLM raises a
    typed ``ValidationError`` the fallback path can catch instead of
    silently passing junk into the Observer.
    """

    model_config = ConfigDict(extra="forbid")

    investigate: bool
    project: str
    window_minutes: int = Field(ge=1, le=240)
    reason: str = Field(max_length=280)
    signals: list[str] = Field(default_factory=list)


def adk_available() -> bool:
    """Return True when the optional ``google-adk`` package is importable."""
    return importlib.util.find_spec("google.adk") is not None


def triage_disabled_reason(config: NengokConfig) -> str | None:
    """
    Explain why triage will not run, or return None when it can.

    `nengok doctor` surfaces this verbatim so an operator can tell
    apart "I turned it off", "the adk extra is missing", and "Phoenix
    MCP cannot start" without reading orchestrator logs.
    """
    if not config.triage_enabled:
        return "disabled in config (triage_enabled = false)"
    if not adk_available():
        return f"the adk extra is not installed; run {ADK_INSTALL_HINT}"
    if shutil.which(config.mcp_npx_command) is None:
        return (
            f"'{config.mcp_npx_command}' is not on PATH, so the Phoenix MCP "
            "toolset cannot start; install Node 18+ (with npx)"
        )
    return None


@dataclass
class TriageAgent:
    """Sync facade the orchestrator holds; builds a fresh ADK runner per call."""

    config: NengokConfig

    def run(self) -> TriageVerdict:
        return run_triage(self.config)


def run_triage(config: NengokConfig, *, runner_factory: RunnerFactory | None = None) -> TriageVerdict:
    """
    Run one triage pass and return the parsed verdict.

    The whole ADK interaction (MCP subprocess spawn included) runs under
    ``asyncio.wait_for`` with ``config.triage_timeout_seconds`` so a hung
    Node subprocess cannot stall the cycle. A verdict that fails schema
    validation is retried once with a fresh session; the second failure
    propagates as ``ValidationError`` for the orchestrator's fallback.

    Refuses to run inside ``ConnectionFactory.begin()`` for the same
    reason ``call_gemini`` does: an LLM call under an open transaction
    would hold a row lock against the operator's pool.
    """
    from nengok.state.connection import in_transaction

    if in_transaction():
        raise RuntimeError(
            "Cannot run triage from inside a database transaction; "
            "close the transaction first, run triage, then open a new "
            "transaction for the result."
        )

    factory = runner_factory or _build_runner

    async def _bounded() -> TriageVerdict:
        return await asyncio.wait_for(
            _run_triage_async(config, factory),
            timeout=config.triage_timeout_seconds,
        )

    try:
        return asyncio.run(_bounded())
    except ValidationError:
        logger.warning("Triage verdict failed schema validation; retrying once with a fresh session")
        return asyncio.run(_bounded())


async def _run_triage_async(config: NengokConfig, factory: RunnerFactory) -> TriageVerdict:
    runner = factory(config)
    try:
        session = await runner.session_service.create_session(
            app_name=TRIAGE_APP_NAME, user_id=TRIAGE_USER_ID
        )
        final_text: str | None = None
        async for event in runner.run_async(
            user_id=TRIAGE_USER_ID,
            session_id=session.id,
            new_message=_build_user_message(config),
        ):
            text = _final_response_text(event)
            if text is not None:
                final_text = text
        if final_text is None:
            raise TriageError("Triage agent finished without a final response.")
        return _parse_verdict(final_text)
    finally:
        await _close_runner(runner)


def _build_runner(config: NengokConfig) -> Any:
    """
    Construct the ADK ``Runner`` with the Phoenix MCP toolset attached.

    The Phoenix base URL and API key reach the MCP subprocess through
    environment variables, the same channel the preflight check in
    ``nengok/phoenix/mcp.py`` uses, so the key never appears in the
    process argument list.
    """
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools.mcp_tool.mcp_toolset import (
            MCPToolset,
            StdioConnectionParams,
            StdioServerParameters,
        )
    except ImportError as exc:
        raise OptionalDependencyError(
            "The ADK triage agent needs the google-adk package. "
            f"Install it with `{ADK_INSTALL_HINT}` or disable triage with "
            "`triage_enabled = false` in ~/.nengok/config.toml.",
            install_hint=ADK_INSTALL_HINT,
        ) from exc

    phoenix_mcp = MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=config.mcp_npx_command,
                args=["-y", config.mcp_package],
                env=_mcp_env(config),
            ),
            timeout=config.mcp_startup_timeout,
        )
    )

    agent = LlmAgent(
        model=config.triage_model,
        name=TRIAGE_AGENT_NAME,
        instruction=_load_triage_prompt(),
        tools=[phoenix_mcp],
        output_schema=TriageVerdict,
    )
    return Runner(
        app_name=TRIAGE_APP_NAME,
        agent=agent,
        session_service=InMemorySessionService(),
    )


def _mcp_env(config: NengokConfig) -> dict[str, str]:
    env = dict(os.environ)
    env["PHOENIX_BASE_URL"] = config.phoenix_base_url
    if config.phoenix_api_key:
        env["PHOENIX_API_KEY"] = config.phoenix_api_key
    return env


def _load_triage_prompt() -> str:
    return TRIAGE_PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_message(config: NengokConfig) -> Any:
    """
    Wrap the cycle request as a genai ``Content`` when the SDK is present.

    ``google-adk`` always installs ``google-genai``, so the real path has
    the typed message. The plain-string fallback exists for unit tests
    that drive a fake runner without either package installed.
    """
    text = (
        f"Inspect the Phoenix project '{config.project_identifier}' over the "
        f"last {config.triage_lookback_minutes} minutes and return your "
        "triage verdict as JSON."
    )
    try:
        from google.genai import types as genai_types
    except ImportError:
        return text
    return genai_types.Content(role="user", parts=[genai_types.Part(text=text)])


def _final_response_text(event: Any) -> str | None:
    """Pull the text of a final-response event, duck-typed for fakes."""
    is_final = getattr(event, "is_final_response", None)
    if callable(is_final) and not is_final():
        return None
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    chunks = [part.text for part in parts if getattr(part, "text", None)]
    if not chunks:
        return None
    return "\n".join(chunks)


def _parse_verdict(text: str) -> TriageVerdict:
    return TriageVerdict.model_validate_json(_strip_fences(text))


def _strip_fences(text: str) -> str:
    """Drop a single ```json fence the model may wrap the verdict in."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def _close_runner(runner: Any) -> None:
    """Release the runner's MCP subprocess; tolerate fakes without close()."""
    close = getattr(runner, "close", None)
    if close is None:
        return
    with contextlib.suppress(Exception):
        result = close()
        if inspect.isawaitable(result):
            await result
