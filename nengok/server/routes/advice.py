"""Clustering-advice endpoints: list retro proposals, activate one per project."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from nengok.reviewer import resolve_reviewer
from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/advice", tags=["advice"])


class AdviceActivate(BaseModel):
    reviewer: str | None = None


@router.get("")
def list_advice(
    store: StoreDep,
    status: Annotated[str | None, Query()] = None,
    project: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return store.list_clustering_advice(project=project, status=status)


@router.post("/{advice_id}/activate")
def activate_advice(advice_id: str, body: AdviceActivate, store: StoreDep) -> dict:
    """
    Activate one proposed amendment, retiring the project's prior active row.

    The reviewer identity is recorded with the decision, mirroring the
    approval audit trail: the agent proposes, the human disposes.
    """
    resolved, _reviewer_source = resolve_reviewer(body.reviewer)
    row = store.activate_clustering_advice(advice_id=advice_id, decided_by=resolved)
    if row is None:
        raise HTTPException(status_code=404, detail="Advice not found")
    return row
