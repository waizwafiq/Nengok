"""Bearer-token guard for `/api/v1/*` dashboard routes."""

from __future__ import annotations

from fastapi import HTTPException, Request, status


def require_dashboard_token(request: Request) -> None:
    """
    Reject requests when `dashboard_auth_token` is set and the header is wrong.

    When no token is configured the dependency is a pass-through, so local
    development keeps working without explicit auth. Mounted as an
    include_router dependency so every route under `/api/v1` inherits it
    without each handler having to opt in.
    """
    expected = getattr(request.app.state.config, "dashboard_auth_token", None)
    if not expected:
        return

    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or presented.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
