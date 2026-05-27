"""Human-in-the-loop approval endpoints and the audit-log feed."""

from __future__ import annotations

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
    approval_id = store.record_approval(
        cluster_id=cluster_id,
        decision=decision,
        reviewer=reviewer,
        reason=reason,
    )
    store.mark_status(cluster_id, _DECISION_TO_STATUS[decision])
    return {
        "approval_id": approval_id,
        "cluster_id": cluster_id,
        "status": _DECISION_TO_STATUS[decision].value,
    }


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
