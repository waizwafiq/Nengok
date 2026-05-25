"""Experiment summary endpoints backed by the local state store."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/{cluster_id}/latest")
def latest_experiment(cluster_id: str, store: StoreDep) -> dict:
    row = store.latest_experiment(cluster_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No experiment recorded for cluster")
    return row
