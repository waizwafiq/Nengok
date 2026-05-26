"""
Per-IP rate limiting for the dashboard `/api/v1/*` surface.

Wraps `slowapi.Limiter` in a small middleware so we can exempt loopback
addresses (where the dashboard owner runs `curl localhost:8765`
unconstrained) and skip any path that is not under the API prefix.

slowapi 0.1.9 ships `SlowAPIMiddleware` but does not expose a per-path
or per-IP exemption hook, so we drive the limiter directly instead of
mounting that middleware. The storage, key extraction, and limit
accounting still live inside `slowapi`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

DEFAULT_API_PREFIX = "/api/v1"
DEFAULT_RATE_LIMIT = "60/minute"
DEFAULT_RETRY_AFTER_SECONDS = 60
LOOPBACK_ADDRESSES: frozenset[str] = frozenset({"127.0.0.1", "::1"})


def build_limiter(rate_limit: str = DEFAULT_RATE_LIMIT) -> Limiter:
    """Construct the dashboard limiter with the configured default."""
    return Limiter(
        key_func=get_remote_address,
        default_limits=[rate_limit],
        headers_enabled=True,
    )


class DashboardRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Enforce a per-IP rate limit on `/api/v1/*` only.

    Loopback addresses (`127.0.0.1`, `::1`) bypass the check so the
    dashboard owner is never throttled on their own laptop. Requests to
    non-API paths (static assets, `/health`, `/metrics`) pass straight
    through.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        limiter: Limiter,
        api_prefix: str = DEFAULT_API_PREFIX,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._api_prefix = api_prefix

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._limiter.enabled or not request.url.path.startswith(self._api_prefix):
            return await call_next(request)

        if get_remote_address(request) in LOOPBACK_ADDRESSES:
            return await call_next(request)

        try:
            self._limiter._check_request_limit(request, None, in_middleware=True)
        except RateLimitExceeded as exc:
            return rate_limit_exceeded_response(request, exc)

        response = await call_next(request)
        view_limit = getattr(request.state, "view_rate_limit", None)
        if view_limit is not None:
            response = self._limiter._inject_headers(response, view_limit)
        return response


def rate_limit_exceeded_response(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    JSON-shaped 429 response with a `Retry-After` header.

    Cloud Run, browsers, and curl-based clients all honour `Retry-After`,
    so we expose it on every throttle. The body is JSON to match the
    rest of the dashboard API surface.
    """
    limit_value = str(exc.detail) if exc.detail else DEFAULT_RATE_LIMIT
    body = {
        "error": "rate_limit_exceeded",
        "detail": f"Rate limit exceeded: {limit_value}.",
        "limit": limit_value,
    }
    response = JSONResponse(status_code=429, content=body)
    response.headers["Retry-After"] = str(DEFAULT_RETRY_AFTER_SECONDS)
    return response
