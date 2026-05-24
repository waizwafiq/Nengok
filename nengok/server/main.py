"""
Bundled FastAPI app that serves the local approval dashboard.

The dashboard is intentionally a single-process, single-user surface.
It binds to 127.0.0.1 by default, mounts the pre-built Vite frontend
under `/`, and exposes the cluster / experiment / approval routes
under `/api/v1`.

Static assets live in two possible locations:

* `nengok/server/static/`: populated by `hatch_build.py` during wheel
  build. This is what pip-installed users hit.
* `frontend/dist/` at the repo root: populated by `npm run build`
  during local development. Used as a fallback when running from a
  source checkout without having reinstalled.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from nengok import __version__
from nengok.config import NengokConfig
from nengok.server.routes import approvals, artifacts, clusters, experiments
from nengok.utils.logging import get_logger

_PACKAGE_STATIC_DIR = Path(__file__).resolve().parent / "static"
_REPO_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

logger = get_logger(__name__)


class _SpaStaticFiles(StaticFiles):
    """
    Static file handler that falls back to index.html on 404.

    Without this, hard refreshing or deep-linking to a client-side
    route like /overview returns FastAPI's default JSON 404 instead
    of letting React Router handle the path.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def _resolve_frontend_dir() -> Path | None:
    if _PACKAGE_STATIC_DIR.is_dir():
        return _PACKAGE_STATIC_DIR
    if _REPO_FRONTEND_DIST.is_dir():
        return _REPO_FRONTEND_DIST
    return None


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

    frontend_dir = _resolve_frontend_dir()
    if frontend_dir is not None:
        logger.info("serving dashboard assets from %s", frontend_dir)
        app.mount("/", _SpaStaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        logger.warning(
            "dashboard assets not found; API routes will work but / will return JSON. "
            "Reinstall nengok from a wheel, or run `cd frontend && npm install && npm run build`."
        )

        @app.get("/", include_in_schema=False)
        def _missing_frontend() -> dict[str, str]:
            return {
                "error": "Nengok dashboard assets are not bundled with this install.",
                "hint": (
                    "Reinstall nengok from a wheel, or from a source checkout run "
                    "`cd frontend && npm install && npm run build`."
                ),
                "api_docs": "/docs",
            }

    return app
