"""
Write incident markdown under `artifacts/incidents/<iso>/`.

Incidents are the operator-facing record of why a cycle paused,
escalated, or aborted. Phase 5 covers three sources: Phoenix timeouts
that escalate a single cluster, cost-budget aborts that stop the
remaining clusters, and circuit-breaker trips that pause the watch
loop. Each writes a single markdown file the dashboard surfaces under
the cluster or the cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def write_incident(
    *,
    artifacts_dir: Path,
    filename: str,
    title: str,
    body: str,
) -> Path:
    """
    Persist an incident markdown file and return its path.

    The directory is timestamped so multiple incidents in one cycle
    sort together. Callers pick `filename` so distinct incident kinds
    do not collide.
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    incident_dir = artifacts_dir / "incidents" / timestamp
    incident_dir.mkdir(parents=True, exist_ok=True)
    path = incident_dir / filename
    rendered = f"# {title}\n\nRecorded at {datetime.now(UTC).isoformat()}.\n\n{body}\n"
    path.write_text(rendered, encoding="utf-8")
    return path
