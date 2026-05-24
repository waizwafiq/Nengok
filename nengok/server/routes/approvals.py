"""Human-in-the-loop approval endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from nengok.core.types import ClusterStatus
from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalCreate(BaseModel):
    cluster_id: str
    decision: Literal["approved", "rejected", "dismissed"]
    decided_by: str | None = None
    notes: str | None = None


@router.post("")
def create_approval(body: ApprovalCreate, store: StoreDep) -> dict:
    approval_id = store.record_approval(
        cluster_id=body.cluster_id,
        decision=body.decision,
        decided_by=body.decided_by,
        notes=body.notes,
    )

    new_status = {
        "approved": ClusterStatus.APPROVED,
        "rejected": ClusterStatus.REJECTED,
        "dismissed": ClusterStatus.DISMISSED,
    }[body.decision]
    store.mark_status(body.cluster_id, new_status)

    return {"approval_id": approval_id, "cluster_id": body.cluster_id, "status": new_status.value}
