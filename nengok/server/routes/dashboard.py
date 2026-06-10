"""Executive dashboard aggregates for the Overview page."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from nengok.server.dependencies import StoreDep

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(
    store: StoreDep,
    project: Annotated[str | None, Query()] = None,
) -> dict:
    return store.dashboard_overview(project=project)
