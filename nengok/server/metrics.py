"""
Optional Prometheus metrics for the dashboard server.

Gated behind `NengokConfig.metrics_enabled`. Counters live on the
module-level `CollectorRegistry` Prometheus ships by default, so the
text exposition includes both Nengok counters and the process
collector Prometheus auto-registers.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

cycles_total = Counter(
    "nengok_cycles_total",
    "Completed orchestrator cycles, labeled by terminal status.",
    labelnames=("status",),
)

clusters_total = Counter(
    "nengok_clusters_total",
    "Cluster lifecycle transitions, labeled by status.",
    labelnames=("status",),
)

gemini_tokens_total = Counter(
    "nengok_gemini_tokens_total",
    "Gemini tokens consumed, labeled by orchestrator stage.",
    labelnames=("stage",),
)

cycle_duration_seconds = Histogram(
    "nengok_cycle_duration_seconds",
    "Wall-clock duration of each orchestrator stage.",
    labelnames=("stage",),
)


def render_text() -> tuple[bytes, str]:
    """Return the Prometheus text exposition and its Content-Type."""
    return generate_latest(), CONTENT_TYPE_LATEST
