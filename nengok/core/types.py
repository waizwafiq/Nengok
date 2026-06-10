"""
Pydantic models that cross every layer of the Nengok loop.

Keep these dependency-free of the Phoenix SDK so the dashboard, the
state store, and tests can all reuse them without dragging in the
upstream client.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClusterStatus(str, Enum):
    OPEN = "open"
    DIAGNOSED = "diagnosed"
    FIX_PROPOSED = "fix_proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


class EvaluatorKind(str, Enum):
    CODE = "code"
    LLM_JUDGE = "llm_judge"


class TraceSpan(BaseModel):
    """A single Phoenix span, normalized to what Nengok actually uses."""

    model_config = ConfigDict(extra="ignore")

    span_id: str
    trace_id: str
    name: str
    span_kind: str | None = None
    session_id: str | None = None
    status_code: str | None = None
    latency_ms: float | None = None
    input_value: str | None = None
    output_value: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None


class AnomalySignal(str, Enum):
    LOW_EVAL_SCORE = "low_eval_score"
    HIGH_LATENCY = "high_latency"
    ERROR_STATUS = "error_status"
    TOOL_FAILURE = "tool_failure"
    MISSING_OUTPUT_FIELD = "missing_output_field"


class AnomalousSpan(BaseModel):
    span: TraceSpan
    signals: list[AnomalySignal]


class RootCauseHypothesis(BaseModel):
    summary: str
    expected_behavior: str
    actual_behavior: str
    likely_cause: str
    implicated_tools: list[str] = Field(default_factory=list)


class Cluster(BaseModel):
    cluster_id: str
    name: str
    description: str
    status: ClusterStatus
    member_span_ids: list[str]
    exemplar_span_ids: list[str]
    hypothesis: RootCauseHypothesis | None = None
    created_at: datetime
    updated_at: datetime
    signals: list[str] = Field(default_factory=list)


class RegressionTestCase(BaseModel):
    case_id: str
    input: dict[str, Any]
    expected: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptProposal(BaseModel):
    cluster_id: str
    baseline_prompt: str
    proposed_prompt: str
    rationale: str


class ExperimentResult(BaseModel):
    experiment_name: str
    experiment_id: str | None = None
    dataset_name: str
    baseline_pass_rate: float
    fix_pass_rate: float
    golden_baseline_pass_rate: float
    golden_fix_pass_rate: float
    per_case: list[dict[str, Any]] = Field(default_factory=list)


class VerificationOutcome(str, Enum):
    PASSED = "passed"
    FAILED_REGRESSION = "failed_regression"
    FAILED_GOLDEN = "failed_golden"


class Verification(BaseModel):
    outcome: VerificationOutcome
    experiment: ExperimentResult
    notes: str | None = None


class FixArtifact(BaseModel):
    cluster_id: str
    prompt_path: str
    dataset_path: str
    rca_path: str
    verification: Verification


class CycleResult(BaseModel):
    clusters_detected: int
    fixes_proposed: int
    escalations: int
    artifacts: list[FixArtifact] = Field(default_factory=list)


class CycleStatus(str, Enum):
    OK = "ok"
    OVER_BUDGET = "over_budget"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    SKIPPED_BY_TRIAGE = "skipped_by_triage"


class CycleRecord(BaseModel):
    """
    Per-cycle bookkeeping row persisted by `StateStore.record_cycle`.

    The orchestrator builds one of these at the end of every cycle,
    success or failure, so the overview dashboard can plot status and
    spend trends without re-reading the meta-tracer spans.
    """

    cycle_id: str
    started_at: datetime
    ended_at: datetime
    status: CycleStatus
    clusters_processed: int = 0
    clusters_discovered: int = 0
    gemini_tokens: int = 0
    gemini_dollars: float = 0.0
    error_message: str | None = None
