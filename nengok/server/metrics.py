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

triage_total = Counter(
    "nengok_triage_total",
    "Triage decisions, labeled by path (adk|fallback) and outcome (investigate|skip).",
    labelnames=("path", "outcome"),
)

triage_duration_seconds = Histogram(
    "nengok_triage_duration_seconds",
    "Wall-clock duration of the triage gate per cycle.",
)

triage_errors_total = Counter(
    "nengok_triage_errors_total",
    "Triage failures that fell back to the deterministic filter, labeled by error class.",
    labelnames=("error_class",),
)


def triage_path_counts() -> dict[str, float]:
    """
    Sum the triage counter by path for this process.

    `/health` uses this to surface the adk-to-fallback ratio; a flip to
    mostly-fallback is the early warning that the ADK path is broken.
    """
    counts = {"adk": 0.0, "fallback": 0.0}
    for metric in triage_total.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            path = sample.labels.get("path")
            if path in counts:
                counts[path] += sample.value
    return counts


def render_text() -> tuple[bytes, str]:
    """Return the Prometheus text exposition and its Content-Type."""
    return generate_latest(), CONTENT_TYPE_LATEST
