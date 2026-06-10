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


@router.get("/{cluster_id}/links")
def get_cluster_links(cluster_id: str, store: StoreDep) -> list[dict]:
    """Cross-agent links for the "Also affects" panel, newest first."""
    clusters = store.list_clusters()
    if not any(c["cluster_id"] == cluster_id for c in clusters):
        raise HTTPException(status_code=404, detail="Cluster not found")
    return [
        {
            "link_id": row["link_id"],
            "linked_cluster_id": row["linked_cluster_id"],
            "linked_name": row["linked_name"],
            "linked_project": row["linked_project"],
            "linked_status": row["linked_status"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "created_at": row["created_at"],
        }
        for row in store.list_cluster_links(cluster_id)
    ]
