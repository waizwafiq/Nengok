"""Pre-redacted, immutable event DTOs dispatched to notifiers.

No field in these dataclasses may contain raw span input/output, full RCA
text, prompt diffs, regression bodies, or artifact bodies. The orchestrator
applies baseline redaction before constructing events; notifiers may apply
additional redaction but cannot un-redact anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExperimentSummary:
    baseline_pass_rate: float
    fix_pass_rate: float
    golden_baseline_pass_rate: float
    golden_fix_pass_rate: float


@dataclass(frozen=True)
class FixProposedEvent:
    cluster_id: str
    cluster_name: str
    status: str
    hypothesis_summary: str | None
    experiment_summary: ExperimentSummary
    artifact_manifest_ref: str
    dashboard_url: str | None
    event_kind: str = field(default="fix_proposed")


@dataclass(frozen=True)
class EscalationEvent:
    cluster_id: str
    cluster_name: str
    status: str
    reason: str | None
    dashboard_url: str | None
    event_kind: str = field(default="escalation")
