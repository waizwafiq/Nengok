"""Executive dashboard aggregates for the Overview page."""

from __future__ import annotations

from fastapi import APIRouter

from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(store: StoreDep) -> dict:
    return store.dashboard_overview()
