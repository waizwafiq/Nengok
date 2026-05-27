"""Human-in-the-loop approval endpoints and the audit-log feed."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from nengok.core.types import ClusterStatus
from nengok.server.dependencies import StoreDep

router = APIRouter(tags=["approvals"])


ApprovalDecision = Literal["approved", "rejected", "dismissed", "escalated"]


_DECISION_TO_STATUS: dict[str, ClusterStatus] = {
    "approved": ClusterStatus.APPROVED,
    "rejected": ClusterStatus.REJECTED,
    "dismissed": ClusterStatus.DISMISSED,
    "escalated": ClusterStatus.ESCALATED,
}


REVIEWER_ENV_VAR = "NENGOK_REVIEWER"
REVIEWER_FILE_PATH = Path.home() / ".nengok" / "reviewer.txt"
ANONYMOUS_REVIEWER = "anonymous"


def resolve_reviewer(provided: str | None) -> tuple[str, str]:
    """
    Return the reviewer string to record plus its provenance.

    Order: explicit body field, then `~/.nengok/reviewer.txt`
    (managed by `nengok reviewer set`), then `NENGOK_REVIEWER`,
    then the literal "anonymous". File wins over env so a per-user
    CLI identity is not silently overridden by a deployment-wide
    env var.
    """
    if provided:
        trimmed = provided.strip()
        if trimmed:
            return trimmed, "request"
    if REVIEWER_FILE_PATH.is_file():
        file_value = REVIEWER_FILE_PATH.read_text(encoding="utf-8").strip()
        if file_value:
            return file_value, "file"
    env_value = os.environ.get(REVIEWER_ENV_VAR, "").strip()
    if env_value:
        return env_value, "env"
    return ANONYMOUS_REVIEWER, "fallback"


class ApprovalCreate(BaseModel):
    decision: ApprovalDecision
    reviewer: str | None = None
    reason: str | None = None


class LegacyApprovalCreate(BaseModel):
    """Body shape accepted by the original `POST /approvals` route."""

    cluster_id: str
    decision: ApprovalDecision
    reviewer: str | None = Field(default=None, alias="decided_by")
    reason: str | None = Field(default=None, alias="notes")

    model_config = {"populate_by_name": True}


class ApprovalResponse(BaseModel):
    approval_id: str
    cluster_id: str
    decision: ApprovalDecision
    reviewer: str | None
    reason: str | None
    created_at: str


def _record(
    store: StoreDep, *, cluster_id: str, decision: str, reviewer: str | None, reason: str | None
) -> dict:
    resolved, source = resolve_reviewer(reviewer)
    approval_id = store.record_approval(
        cluster_id=cluster_id,
        decision=decision,
        reviewer=resolved,
        reason=(reason.strip() if reason else None) or None,
    )
    store.mark_status(cluster_id, _DECISION_TO_STATUS[decision])
    return {
        "approval_id": approval_id,
        "cluster_id": cluster_id,
        "status": _DECISION_TO_STATUS[decision].value,
        "reviewer": resolved,
        "reviewer_source": source,
    }


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
    )


@router.post("/approvals")
def create_approval(body: LegacyApprovalCreate, store: StoreDep) -> dict:
    return _record(
        store,
        cluster_id=body.cluster_id,
        decision=body.decision,
        reviewer=body.reviewer,
        reason=body.reason,
    )


def _cluster_exists(store: StoreDep, cluster_id: str) -> bool:
    return any(c["cluster_id"] == cluster_id for c in store.list_clusters())
