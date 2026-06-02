"""
Async HTTPX wrapper that targets the same `/api/v1/*` routes as the browser dashboard.

Sharing the wire format with the FastAPI app keeps the two operator
surfaces from drifting on field names, status values, or pagination
behaviour. Every method here calls a route that the dashboard already
exercises in production.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx

DEFAULT_TIMEOUT_SECONDS: float = 10.0
APPROVAL_SOURCE_TUI: str = "tui"


class TuiApiError(RuntimeError):
    """Raised when the FastAPI server returns a non-2xx response the TUI cannot recover from."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TuiApiClient:
    """Thin async wrapper used by every TUI screen."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"
        self._timeout_seconds = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    @asynccontextmanager
    async def _client(self):
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout_seconds,
        ) as client:
            yield client

    async def ping(self) -> dict[str, Any]:
        """Hit `/health` once to confirm the server is reachable."""
        async with self._client() as client:
            response = await client.get("/health")
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, dict)
            return payload

    async def list_clusters(self) -> list[dict[str, Any]]:
        async with self._client() as client:
            response = await client.get("/api/v1/clusters")
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, list)
            return payload

    async def get_cluster(self, cluster_id: str) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(f"/api/v1/clusters/{cluster_id}")
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, dict)
            return payload

    async def latest_experiment(self, cluster_id: str) -> dict[str, Any] | None:
        async with self._client() as client:
            response = await client.get(f"/api/v1/experiments/{cluster_id}/latest")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, dict)
            return payload

    async def get_artifacts(self, cluster_id: str) -> dict[str, Any] | None:
        async with self._client() as client:
            response = await client.get(f"/api/v1/artifacts/{cluster_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
            assert isinstance(payload, dict)
            return payload

    async def submit_approval(
        self,
        cluster_id: str,
        *,
        decision: str,
        reviewer: str | None,
        reason: str | None,
        source: str = APPROVAL_SOURCE_TUI,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"decision": decision, "source": source}
        if reviewer is not None:
            body["reviewer"] = reviewer
        if reason is not None:
            body["reason"] = reason
        async with self._client() as client:
            response = await client.post(
                f"/api/v1/clusters/{cluster_id}/approvals",
                json=body,
            )
            if response.status_code >= 400:
                detail = _extract_detail(response)
                raise TuiApiError(detail, status_code=response.status_code)
            payload = response.json()
            assert isinstance(payload, dict)
            return payload


def _extract_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error")
        if isinstance(detail, str):
            return detail
    return f"HTTP {response.status_code}"
