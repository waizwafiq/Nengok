"""SQLite state-store smoke tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nengok.core.types import AnomalousSpan, AnomalySignal, Cluster, ClusterStatus, TraceSpan
from nengok.state.store import StateStore


def _anomaly(span_id: str) -> AnomalousSpan:
    return AnomalousSpan(
        span=TraceSpan(
            span_id=span_id,
            trace_id=f"t-{span_id}",
            name="agent.respond",
        ),
        signals=[AnomalySignal.ERROR_STATUS],
    )


def test_deduplicate_filters_seen_spans(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    first = store.deduplicate([_anomaly("s1"), _anomaly("s2")])
    second = store.deduplicate([_anomaly("s1"), _anomaly("s2"), _anomaly("s3")])

    assert [a.span.span_id for a in first] == ["s1", "s2"]
    assert [a.span.span_id for a in second] == ["s3"]


def test_cluster_upsert_round_trip(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.db")
    now = datetime.now(timezone.utc)
    cluster = Cluster(
        cluster_id="c-1",
        name="flights-schema-drift",
        description="Schema drift in flights API",
        status=ClusterStatus.OPEN,
        member_span_ids=["s1"],
        exemplar_span_ids=["s1"],
        created_at=now,
        updated_at=now,
    )

    store.upsert_cluster(cluster)
    store.mark_status("c-1", ClusterStatus.DIAGNOSED)

    rows = store.list_clusters()
    assert len(rows) == 1
    assert rows[0]["status"] == "diagnosed"
