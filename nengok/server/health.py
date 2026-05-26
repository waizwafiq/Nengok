"""
Unauthenticated `/health` endpoint for infrastructure probes.

Cloud Run, Kubernetes liveness checks and uptime monitors all expect a
top-level `/health` that returns the current liveness of the process
and the reachability of its dependencies. The shape is fixed:

```
{
    "status": "ok",
    "version": "0.1.0",
    "phoenix_reachable": bool,
    "gemini_reachable": bool,
    "db_writable": bool,
}
```

Phoenix and Gemini reachability cost a real network round-trip and a
1-token Gemini call respectively, so each is cached for 30 seconds.
Probes that fire every few seconds therefore see at most two upstream
calls per minute. The SQLite write probe is cheap and runs on every
request.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from nengok import __version__
from nengok.config import NengokConfig
from nengok.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 30.0
DEFAULT_PHOENIX_PROBE_TIMEOUT_SECONDS = 3.0
GEMINI_HEALTH_MODEL = "gemini-2.5-flash"

ReachabilityCheck = Callable[[NengokConfig], bool]


@dataclass
class _CacheEntry:
    expires_at: float
    value: bool


class HealthChecker:
    """Compute and cache the `/health` payload."""

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        phoenix_check: ReachabilityCheck | None = None,
        gemini_check: ReachabilityCheck | None = None,
        db_check: ReachabilityCheck | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._phoenix_check = phoenix_check or check_phoenix_reachable
        self._gemini_check = gemini_check or check_gemini_reachable
        self._db_check = db_check or check_db_writable
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}

    def snapshot(self, config: NengokConfig) -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "phoenix_reachable": self._cached("phoenix", lambda: self._phoenix_check(config)),
            "gemini_reachable": self._cached("gemini", lambda: self._gemini_check(config)),
            "db_writable": bool(self._db_check(config)),
        }

    def reset(self) -> None:
        with self._lock:
            self._cache.clear()

    def _cached(self, key: str, compute: Callable[[], bool]) -> bool:
        now = self._clock()
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.expires_at > now:
                return entry.value
        value = bool(compute())
        with self._lock:
            self._cache[key] = _CacheEntry(expires_at=now + self._cache_ttl_seconds, value=value)
        return value


def check_phoenix_reachable(
    config: NengokConfig,
    *,
    timeout_seconds: float = DEFAULT_PHOENIX_PROBE_TIMEOUT_SECONDS,
) -> bool:
    base_url = config.phoenix_base_url.rstrip("/") + "/"
    url = urljoin(base_url, "v1/projects")
    request = urllib.request.Request(url, method="GET")
    if config.phoenix_api_key:
        request.add_header("Authorization", f"Bearer {config.phoenix_api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.getcode())
            return 200 <= status_code < 300
    except urllib.error.HTTPError as exc:
        logger.debug("phoenix health probe returned HTTP %s", exc.code)
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("phoenix health probe failed: %s", exc)
        return False


def check_gemini_reachable(config: NengokConfig) -> bool:
    if not config.google_api_key:
        return False
    try:
        from google import genai
    except ImportError as exc:
        logger.debug("gemini health probe skipped, google-genai not installed: %s", exc)
        return False
    try:
        client = genai.Client(api_key=config.google_api_key)
        client.models.generate_content(
            model=GEMINI_HEALTH_MODEL,
            contents="ping",
            config={"max_output_tokens": 1},
        )
    except Exception as exc:
        logger.debug("gemini health probe failed: %s", exc)
        return False
    return True


def check_db_writable(config: NengokConfig) -> bool:
    db_path = Path(config.state_db_path)
    parent = db_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("db health probe could not create %s: %s", parent, exc)
        return False

    sentinel = parent / ".nengok-health-probe"
    try:
        sentinel.write_bytes(b"ok")
    except OSError as exc:
        logger.debug("db health probe could not write sentinel %s: %s", sentinel, exc)
        return False
    finally:
        with contextlib.suppress(OSError):
            sentinel.unlink(missing_ok=True)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        logger.debug("db health probe could not open %s: %s", db_path, exc)
        return False
    return True
