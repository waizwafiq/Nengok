"""Cluster listing + detail endpoints used by the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from nengok.core.types import ClusterStatus
from nengok.server.dependencies import get_store
from nengok.state.store import StateStore

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("")
def list_clusters(
    status: ClusterStatus | None = Query(default=None),
    store: StateStore = Depends(get_store),
) -> list[dict]:
    return store.list_clusters(status=status)


@router.get("/{cluster_id}")
def get_cluster(cluster_id: str, store: StateStore = Depends(get_store)) -> dict:
    clusters = store.list_clusters()
    match = next((c for c in clusters if c["cluster_id"] == cluster_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return match
