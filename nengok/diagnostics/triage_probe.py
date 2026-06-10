"""
Report whether the ADK triage gate can run.

Surfaces ``triage_disabled_reason`` so an operator can tell apart "I
turned it off", "the adk extra is missing", and "the Phoenix MCP
toolset cannot start" from one doctor line instead of grepping
orchestrator logs for the startup warning.
"""

from __future__ import annotations

from nengok.agents.triage import ADK_INSTALL_HINT, triage_disabled_reason
from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus

PROBE_NAME = "triage"


def probe_triage(config: NengokConfig) -> ProbeResult:
    reason = triage_disabled_reason(config)
    if reason is None:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.OK,
            detail=(
                f"enabled (model {config.triage_model}, "
                f"lookback {config.triage_lookback_minutes}m, "
                f"timeout {config.triage_timeout_seconds:.0f}s)"
            ),
        )

    if not config.triage_enabled:
        return ProbeResult(
            name=PROBE_NAME,
            status=ProbeStatus.OK,
            detail="disabled in config (triage_enabled = false); cycles run the deterministic filter",
        )

    return ProbeResult(
        name=PROBE_NAME,
        status=ProbeStatus.WARN,
        detail=f"enabled in config but cannot run: {reason}",
        fix_hint=(
            f"Install the extra with `{ADK_INSTALL_HINT}` and make sure Node 18+ (with npx) "
            "is on PATH, or set `triage_enabled = false` in ~/.nengok/config.toml."
        ),
    )
