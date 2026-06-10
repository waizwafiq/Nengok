"""Human-in-the-loop approval endpoints and the audit-log feed."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from nengok.core.types import ClusterStatus
from nengok.reviewer import (
    ANONYMOUS_REVIEWER,
    REVIEWER_ENV_VAR,
    REVIEWER_FILE_PATH,
    resolve_reviewer,
)
from nengok.server.dependencies import StoreDep

router = APIRouter(tags=["approvals"])


ApprovalDecision = Literal["approved", "rejected", "dismissed", "escalated"]
ApprovalSource = Literal["dashboard", "tui", "api"]
FeedbackTag = Literal["duplicate_cluster", "mixed_root_causes", "not_a_failure"]


_DECISION_TO_STATUS: dict[str, ClusterStatus] = {
    "approved": ClusterStatus.APPROVED,
    "rejected": ClusterStatus.REJECTED,
    "dismissed": ClusterStatus.DISMISSED,
    "escalated": ClusterStatus.ESCALATED,
}

_DECISION_TO_FEEDBACK_KIND: dict[str, str] = {
    "approved": "fix_approved",
    "rejected": "fix_rejected",
    "dismissed": "cluster_dismissed",
}

_VALID_SOURCES: frozenset[str] = frozenset({"dashboard", "tui", "api"})


__all__ = [
    "ANONYMOUS_REVIEWER",
    "REVIEWER_ENV_VAR",
    "REVIEWER_FILE_PATH",
    "resolve_reviewer",
    "router",
]


class ApprovalCreate(BaseModel):
    decision: ApprovalDecision
    reviewer: str | None = None
    reason: str | None = None
    source: ApprovalSource = "dashboard"
    feedback_tag: FeedbackTag | None = None


class LegacyApprovalCreate(BaseModel):
    """Body shape accepted by the original `POST /approvals` route."""

    cluster_id: str
    decision: ApprovalDecision
    reviewer: str | None = Field(default=None, alias="decided_by")
    reason: str | None = Field(default=None, alias="notes")
    source: ApprovalSource = "api"
    feedback_tag: FeedbackTag | None = None

    model_config = {"populate_by_name": True}


class ApprovalResponse(BaseModel):
    approval_id: str
    cluster_id: str
    decision: ApprovalDecision
    reviewer: str | None
    reason: str | None
    source: ApprovalSource = "dashboard"
    created_at: str


def _record(
    store: StoreDep,
    *,
    cluster_id: str,
    decision: str,
    reviewer: str | None,
    reason: str | None,
    source: str,
    feedback_tag: str | None = None,
) -> dict:
    resolved, reviewer_source = resolve_reviewer(reviewer)
    normalized_source = source if source in _VALID_SOURCES else "dashboard"
    cleaned_reason = (reason.strip() if reason else None) or None
    approval_id = store.record_approval(
        cluster_id=cluster_id,
        decision=decision,
        reviewer=resolved,
        reason=cleaned_reason,
        source=normalized_source,
    )
    store.mark_status(cluster_id, _DECISION_TO_STATUS[decision])
    _record_feedback(
        store,
        cluster_id=cluster_id,
        decision=decision,
        reason=cleaned_reason,
        source=normalized_source,
        feedback_tag=feedback_tag,
    )
    return {
        "approval_id": approval_id,
        "cluster_id": cluster_id,
        "status": _DECISION_TO_STATUS[decision].value,
        "reviewer": resolved,
        "reviewer_source": reviewer_source,
        "source": normalized_source,
    }


def _record_feedback(
    store: StoreDep,
    *,
    cluster_id: str,
    decision: str,
    reason: str | None,
    source: str,
    feedback_tag: str | None,
) -> None:
    """
    Bridge the approval into `nengok_cluster_feedback`.

    An explicit tag (duplicate_cluster / mixed_root_causes /
    not_a_failure) beats the decision-derived kind; an untagged
    rejection still writes `fix_rejected`. Escalations carry no
    clustering signal and write nothing.
    """
    kind = feedback_tag or _DECISION_TO_FEEDBACK_KIND.get(decision)
    if kind is None:
        return
    store.record_cluster_feedback(
        cluster_id=cluster_id,
        kind=kind,
        detail=reason,
        source=source,
    )


@router.get("/reviewer")
def get_reviewer() -> dict[str, str | None]:
    resolved, source = resolve_reviewer(None)
    return {"reviewer": resolved, "source": source}


@router.get("/approvals")
def list_approvals(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[str | None, Query()] = None,
) -> list[ApprovalResponse]:
    return [ApprovalResponse(**row) for row in store.list_approvals(limit=limit, before=before)]


@router.get("/clusters/{cluster_id}/approvals")
def list_cluster_approvals(cluster_id: str, store: StoreDep) -> list[ApprovalResponse]:
    rows = store.list_cluster_approvals(cluster_id)
    if not rows and not _cluster_exists(store, cluster_id):
        raise HTTPException(status_code=404, detail="Cluster not found")
    return [ApprovalResponse(**row) for row in rows]


@router.post("/clusters/{cluster_id}/approvals")
def create_cluster_approval(cluster_id: str, body: ApprovalCreate, store: StoreDep) -> dict:
    if not _cluster_exists(store, cluster_id):
        raise HTTPException(status_code=404, detail="Cluster not found")
    return _record(
        store,
        cluster_id=cluster_id,
        decision=body.decision,
        reviewer=body.reviewer,
        reason=body.reason,
        source=body.source,
        feedback_tag=body.feedback_tag,
    )


@router.post("/approvals")
def create_approval(body: LegacyApprovalCreate, store: StoreDep) -> dict:
    return _record(
        store,
        cluster_id=body.cluster_id,
        decision=body.decision,
        reviewer=body.reviewer,
        reason=body.reason,
        source=body.source,
        feedback_tag=body.feedback_tag,
    )


class MergeWrongCreate(BaseModel):
    span_ids: list[str] = Field(min_length=1)
    reason: str | None = None
    source: ApprovalSource = "dashboard"


@router.post("/clusters/{cluster_id}/feedback/merge-wrong")
def flag_merge_wrong(cluster_id: str, body: MergeWrongCreate, store: StoreDep) -> dict:
    """
    Flag a machine merge as wrong and detach the listed span ids.

    The detached spans also leave `nengok_seen_spans`, so the next cycle
    re-processes them into their own cluster instead of silently
    re-attaching them here.
    """
    if not _cluster_exists(store, cluster_id):
        raise HTTPException(status_code=404, detail="Cluster not found")
    detached = store.detach_spans_from_cluster(cluster_id=cluster_id, span_ids=body.span_ids)
    if detached == 0:
        raise HTTPException(status_code=400, detail="None of the span ids belong to this cluster")
    feedback_id = store.record_cluster_feedback(
        cluster_id=cluster_id,
        kind="merge_wrong",
        detail=(body.reason or f"detached {detached} span(s)"),
        source=body.source,
    )
    return {
        "feedback_id": feedback_id,
        "cluster_id": cluster_id,
        "detached_span_ids": body.span_ids,
        "detached_count": detached,
    }


def _cluster_exists(store: StoreDep, cluster_id: str) -> bool:
    return any(c["cluster_id"] == cluster_id for c in store.list_clusters())
