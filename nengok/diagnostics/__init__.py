"""
Read-only health checks surfaced by `nengok doctor`.

Each probe is a callable that takes the resolved `NengokConfig` and
returns a `ProbeResult`. Keeping the probes separate lets ops add new
ones (PII redactor coverage, Slack webhook reachability, etc.) without
touching the CLI. The default set is collected here so the CLI does
not need to know which modules exist.
"""

from __future__ import annotations

from nengok.diagnostics.agent_runner_probe import probe_agent_runner
from nengok.diagnostics.base import Probe, ProbeResult, ProbeStatus
from nengok.diagnostics.baseline_prompt_probe import probe_baseline_prompt
from nengok.diagnostics.config_probe import probe_config_file
from nengok.diagnostics.db_privileges import probe_db_privileges
from nengok.diagnostics.gemini_probe import probe_gemini
from nengok.diagnostics.phoenix_probe import probe_phoenix
from nengok.diagnostics.phoenix_project_probe import probe_phoenix_project
from nengok.diagnostics.triage_probe import probe_triage

DEFAULT_PROBES: tuple[Probe, ...] = (
    probe_config_file,
    probe_phoenix,
    probe_phoenix_project,
    probe_gemini,
    probe_db_privileges,
    probe_baseline_prompt,
    probe_agent_runner,
    probe_triage,
)

__all__ = [
    "DEFAULT_PROBES",
    "Probe",
    "ProbeResult",
    "ProbeStatus",
    "probe_agent_runner",
    "probe_baseline_prompt",
    "probe_config_file",
    "probe_db_privileges",
    "probe_gemini",
    "probe_phoenix",
    "probe_phoenix_project",
    "probe_triage",
]
