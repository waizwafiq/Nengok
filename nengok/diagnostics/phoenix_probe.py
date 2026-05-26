"""
Confirm Phoenix is reachable and report its version + project count.

The probe issues two cheap GETs against the configured base URL:
``/v1/projects`` confirms auth and reachability, ``/healthz`` (when
available) carries the server version string. Both are wrapped in a
single tight timeout so a hanging Phoenix does not block the rest of
the doctor run.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus

Opener = Callable[[urllib.request.Request, float], Any]


def probe_phoenix(
    config: NengokConfig,
    *,
    opener: Opener | None = None,
    timeout_seconds: float = 5.0,
) -> ProbeResult:
    base_url = config.phoenix_base_url.rstrip("/") + "/"
    request_opener = opener or _default_opener

    projects_url = urljoin(base_url, "v1/projects")
    projects_request = urllib.request.Request(projects_url, method="GET")
    if config.phoenix_api_key:
        projects_request.add_header("Authorization", f"Bearer {config.phoenix_api_key}")

    try:
        response = request_opener(projects_request, timeout_seconds)
    except urllib.error.HTTPError as exc:
        return ProbeResult(
            name="phoenix",
            status=ProbeStatus.FAIL,
            detail=f"HTTP {exc.code} from {projects_url}",
            fix_hint=(
                "Check phoenix_base_url and PHOENIX_API_KEY. "
                "401/403 means auth; 404 means the URL prefix is wrong."
            ),
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return ProbeResult(
            name="phoenix",
            status=ProbeStatus.FAIL,
            detail=f"could not reach {projects_url}: {reason}",
            fix_hint="Start Phoenix (`phoenix serve`) or correct phoenix_base_url.",
        )

    status_code = getattr(response, "status", None) or response.getcode()
    if not 200 <= status_code < 300:
        return ProbeResult(
            name="phoenix",
            status=ProbeStatus.FAIL,
            detail=f"{projects_url} returned {status_code}",
            fix_hint="Phoenix accepted the connection but rejected the request.",
        )

    project_count = _count_projects(response)
    version = _phoenix_version(
        base_url=base_url,
        opener=request_opener,
        timeout_seconds=timeout_seconds,
    )
    version_part = f"version {version}, " if version else ""
    project_part = f"{project_count} projects" if project_count is not None else "reachable"
    return ProbeResult(
        name="phoenix",
        status=ProbeStatus.OK,
        detail=f"{config.phoenix_base_url} ({version_part}{project_part})",
    )


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _count_projects(response: Any) -> int | None:
    """Pull the project count out of the `/v1/projects` body, defensively."""
    body = _read_body(response)
    if body is None:
        return None
    payload = _safe_json(body)
    if payload is None:
        return None
    if isinstance(payload, list):
        return len(payload)
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return len(data)
    return None


def _phoenix_version(
    *,
    base_url: str,
    opener: Opener,
    timeout_seconds: float,
) -> str | None:
    url = urljoin(base_url, "healthz")
    try:
        response = opener(urllib.request.Request(url, method="GET"), timeout_seconds)
    except Exception:
        return None
    body = _read_body(response)
    if not body:
        return None
    payload = _safe_json(body)
    if isinstance(payload, dict):
        for key in ("version", "phoenix_version"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    text = body.strip()
    return text or None


def _read_body(response: Any) -> str | None:
    read = getattr(response, "read", None)
    if read is None:
        return None
    try:
        raw = read()
    except Exception:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _safe_json(body: str) -> Any | None:
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None
