"""Cluster listing + detail endpoints used by the dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from nengok.core.types import ClusterStatus
from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("")
def list_clusters(
    store: StoreDep,
    status: Annotated[ClusterStatus | None, Query()] = None,
    project: Annotated[str | None, Query()] = None,
) -> list[dict]:
    return store.list_clusters(status=status, project=project)


@router.get("/{cluster_id}")
def get_cluster(cluster_id: str, store: StoreDep) -> dict:
    clusters = store.list_clusters()
    match = next((c for c in clusters if c["cluster_id"] == cluster_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return match
