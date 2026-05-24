"""
Bundled FastAPI app that serves the local approval dashboard.

The dashboard is intentionally a single-process, single-user surface.
It binds to 127.0.0.1 by default, mounts the pre-built Vite frontend
under `/`, and exposes the cluster / experiment / approval routes
under `/api/v1`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nengok import __version__
from nengok.config import NengokConfig
from nengok.server.routes import approvals, artifacts, clusters, experiments

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def create_app(*, config: NengokConfig) -> FastAPI:
    """Application factory. Keeps `config` injectable for tests."""
    app = FastAPI(
        title="Nengok Dashboard",
        version=__version__,
        description="Local approval surface for Nengok-proposed fixes.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = config

    app.include_router(clusters.router, prefix="/api/v1")
    app.include_router(experiments.router, prefix="/api/v1")
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(artifacts.router, prefix="/api/v1")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app
