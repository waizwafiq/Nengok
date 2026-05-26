"""
Read-only health checks surfaced by `nengok doctor`.

Each probe is a callable that takes the resolved `NengokConfig` and
returns a `ProbeResult`. Keeping the probes separate lets ops add new
ones (PII redactor coverage, Slack webhook reachability, etc.) without
touching the CLI. The default set is collected here so the CLI does
not need to know which modules exist.
"""

from __future__ import annotations

from nengok.diagnostics.base import Probe, ProbeResult, ProbeStatus

DEFAULT_PROBES: tuple[Probe, ...] = ()

__all__ = [
    "DEFAULT_PROBES",
    "Probe",
    "ProbeResult",
    "ProbeStatus",
]
