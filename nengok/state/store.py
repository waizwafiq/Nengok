"""
SQLite-backed persistence for cluster lifecycle and span deduplication.

We deliberately stay on `sqlite3` (stdlib) — no SQLAlchemy, no Alembic.
The schema is tiny, the volume is tiny, and dragging in a full ORM for
a local SDK is exactly the kind of premature complexity the project
rules forbid.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from nengok.core.types import AnomalousSpan, Cluster, ClusterStatus, ExperimentResult
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


class StateStore:
    """Thin SQLite wrapper. Connection-per-call; no pooling required."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._apply_schema()

    def _apply_schema(self) -> None:
        schema = resources.files("nengok.state").joinpath("schema.sql").read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
            self._migrate_cluster_columns(conn)

    @staticmethod
    def _migrate_cluster_columns(conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(clusters)").fetchall()}
        for column in ("first_seen", "diagnosed_at"):
            if column not in existing:
                conn.execute(f"ALTER TABLE clusters ADD COLUMN {column} TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    def deduplicate(self, anomalies: list[AnomalousSpan]) -> list[AnomalousSpan]:
        if not anomalies:
            return []

        new: list[AnomalousSpan] = []
        now = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            for anomaly in anomalies:
                span_id = anomaly.span.span_id
                row = conn.execute("SELECT 1 FROM seen_spans WHERE span_id = ?", (span_id,)).fetchone()
                if row is not None:
                    continue
                conn.execute(
                    "INSERT INTO seen_spans (span_id, cluster_id, first_seen) VALUES (?, NULL, ?)",
                    (span_id, now),
                )
                new.append(anomaly)
        return new

    def upsert_cluster(self, cluster: Cluster, *, first_seen: datetime | None = None) -> None:
        first_seen_iso = first_seen.isoformat() if first_seen else cluster.created_at.isoformat()
        diagnosed_at_iso = (
            cluster.updated_at.isoformat() if cluster.status is ClusterStatus.DIAGNOSED else None
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clusters
                  (cluster_id, name, description, status, hypothesis_json, member_spans_json,
                   created_at, updated_at, first_seen, diagnosed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    status = excluded.status,
                    hypothesis_json = excluded.hypothesis_json,
                    member_spans_json = excluded.member_spans_json,
                    updated_at = excluded.updated_at,
                    first_seen = COALESCE(clusters.first_seen, excluded.first_seen),
                    diagnosed_at = COALESCE(clusters.diagnosed_at, excluded.diagnosed_at)
                """,
                (
                    cluster.cluster_id,
                    cluster.name,
                    cluster.description,
                    cluster.status.value,
                    cluster.hypothesis.model_dump_json() if cluster.hypothesis else None,
                    json.dumps(cluster.member_span_ids),
                    cluster.created_at.isoformat(),
                    cluster.updated_at.isoformat(),
                    first_seen_iso,
                    diagnosed_at_iso,
                ),
            )

    def mark_status(self, cluster_id: str, status: ClusterStatus) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            if status is ClusterStatus.DIAGNOSED:
                conn.execute(
                    """
                    UPDATE clusters
                    SET status = ?, updated_at = ?, diagnosed_at = COALESCE(diagnosed_at, ?)
                    WHERE cluster_id = ?
                    """,
                    (status.value, now, now, cluster_id),
                )
            else:
                conn.execute(
                    "UPDATE clusters SET status = ?, updated_at = ? WHERE cluster_id = ?",
                    (status.value, now, cluster_id),
                )

    def list_clusters(self, *, status: ClusterStatus | None = None) -> list[dict]:
        query = "SELECT * FROM clusters"
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY updated_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def record_approval(
        self, *, cluster_id: str, decision: str, decided_by: str | None, notes: str | None
    ) -> str:
        approval_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (approval_id, cluster_id, decision, decided_by, decided_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (approval_id, cluster_id, decision, decided_by, now, notes),
            )
        return approval_id

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments
                  (experiment_id, cluster_id, experiment_name, dataset_name,
                   baseline_pass_rate, fix_pass_rate,
                   golden_baseline_pass_rate, golden_fix_pass_rate,
                   per_case_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.experiment_id,
                    cluster_id,
                    result.experiment_name,
                    result.dataset_name,
                    result.baseline_pass_rate,
                    result.fix_pass_rate,
                    result.golden_baseline_pass_rate,
                    result.golden_fix_pass_rate,
                    json.dumps(result.per_case),
                    now,
                ),
            )

    def dashboard_overview(self) -> dict:
        """Aggregated metrics for the executive dashboard panel."""
        with self._connect() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM clusters GROUP BY status"
            ).fetchall()
            by_status: dict[str, int] = {row["status"]: row["n"] for row in status_rows}
            approved = by_status.get(ClusterStatus.APPROVED.value, 0)
            open_count = by_status.get(ClusterStatus.OPEN.value, 0)
            diagnosed = by_status.get(ClusterStatus.DIAGNOSED.value, 0)
            escalated = by_status.get(ClusterStatus.ESCALATED.value, 0)
            active = approved + open_count + diagnosed + escalated
            close_rate = approved / active if active else 0.0

            mttd_row = conn.execute(
                """
                SELECT AVG(
                    (julianday(diagnosed_at) - julianday(first_seen)) * 86400.0
                ) AS seconds
                FROM clusters
                WHERE first_seen IS NOT NULL AND diagnosed_at IS NOT NULL
                """
            ).fetchone()
            mttr_row = conn.execute(
                """
                SELECT AVG(
                    (julianday(a.decided_at) - julianday(c.diagnosed_at)) * 86400.0
                ) AS seconds
                FROM clusters c
                JOIN approvals a ON a.cluster_id = c.cluster_id
                WHERE a.decision = 'approved' AND c.diagnosed_at IS NOT NULL
                """
            ).fetchone()

            regression_row = conn.execute(
                """
                SELECT COALESCE(SUM(json_array_length(per_case_json)), 0) AS total
                FROM experiments
                WHERE row_id IN (
                    SELECT MAX(row_id) FROM experiments GROUP BY cluster_id
                )
                """
            ).fetchone()

            pass_row = conn.execute(
                """
                SELECT AVG(fix_pass_rate) AS pass_rate
                FROM experiments
                WHERE created_at >= datetime('now', '-30 days')
                """
            ).fetchone()

        return {
            "cluster_counts": {
                "open": open_count,
                "diagnosed": diagnosed,
                "fix_proposed": by_status.get(ClusterStatus.FIX_PROPOSED.value, 0),
                "approved": approved,
                "rejected": by_status.get(ClusterStatus.REJECTED.value, 0),
                "dismissed": by_status.get(ClusterStatus.DISMISSED.value, 0),
                "escalated": escalated,
            },
            "mttd_seconds": mttd_row["seconds"],
            "mttr_seconds": mttr_row["seconds"],
            "close_rate": close_rate,
            "regression_test_count": int(regression_row["total"] or 0),
            "fix_pass_rate_30d": pass_row["pass_rate"],
            "gemini_tokens_used_30d": 0,
            "gemini_dollars_used_30d": 0.0,
        }

    def latest_experiment(self, cluster_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT experiment_id, cluster_id, experiment_name, dataset_name,
                       baseline_pass_rate, fix_pass_rate,
                       golden_baseline_pass_rate, golden_fix_pass_rate,
                       per_case_json, created_at
                FROM experiments
                WHERE cluster_id = ?
                ORDER BY created_at DESC, row_id DESC
                LIMIT 1
                """,
                (cluster_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["per_case"] = json.loads(record.pop("per_case_json"))
        return record
