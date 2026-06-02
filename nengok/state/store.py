"""
SQLite-backed persistence for cluster lifecycle and span deduplication.

The schema lives in dialect-portable Alembic revisions under
`nengok/state/alembic/versions/`. Every table is prefixed `nengok_` so
it cannot collide with the operator's existing schema when Nengok
shares a database with their application. The raw `sqlite3` driver
remains here in transition; the relational store will move to
SQLAlchemy Core in a later Phase 14 subphase.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine

from nengok.core.types import (
    AnomalousSpan,
    Cluster,
    ClusterStatus,
    CycleRecord,
    ExperimentResult,
)
from nengok.state.alembic_runner import upgrade_head
from nengok.utils.logging import get_logger

logger = get_logger(__name__)


_ALLOWED_RANGE_COLUMNS = frozenset({"created_at", "started_at", "updated_at"})


def _range_sql(
    base_query: str,
    *,
    column: str,
    since: datetime | None,
    until: datetime | None,
    order_by: str,
) -> tuple[str, tuple]:
    """
    Append a `WHERE column >= ? AND column < ?` filter and an ORDER BY to `base_query`.

    `column` and `order_by` are author-controlled (the allowlist below
    rejects anything that did not come from this module), so the f-string
    composition stays bandit-clean. Every user-supplied value is bound
    through `params` and never spliced into the SQL.
    """
    if column not in _ALLOWED_RANGE_COLUMNS:
        raise ValueError(f"_range_sql refuses unknown column '{column}'")

    clauses: list[str] = []
    params: list = []
    if since is not None:
        clauses.append(f"{column} >= ?")
        params.append(since.isoformat())
    if until is not None:
        clauses.append(f"{column} < ?")
        params.append(until.isoformat())
    sql = base_query.rstrip()
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {order_by}"
    return sql, tuple(params)


class StateStore:
    """Thin SQLite wrapper. Connection-per-call; no pooling required."""

    def __init__(self, db_path: Path, *, schema: str | None = None) -> None:
        self._db_path = db_path
        self._schema = schema
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        """
        Apply every pending Alembic revision against the local SQLite file.

        The store builds a short-lived SQLAlchemy engine to drive
        `alembic upgrade head` and disposes it immediately. The raw
        `sqlite3` connection used by every other method on this class
        is unaffected.
        """
        engine = create_engine(f"sqlite:///{self._db_path.as_posix()}")
        try:
            upgrade_head(engine, schema=self._schema)
        finally:
            engine.dispose()

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
                row = conn.execute("SELECT 1 FROM nengok_seen_spans WHERE span_id = ?", (span_id,)).fetchone()
                if row is not None:
                    continue
                conn.execute(
                    "INSERT INTO nengok_seen_spans (span_id, cluster_id, first_seen) VALUES (?, NULL, ?)",
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
                INSERT INTO nengok_clusters
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
                    first_seen = COALESCE(nengok_clusters.first_seen, excluded.first_seen),
                    diagnosed_at = COALESCE(nengok_clusters.diagnosed_at, excluded.diagnosed_at)
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
                    UPDATE nengok_clusters
                    SET status = ?, updated_at = ?, diagnosed_at = COALESCE(diagnosed_at, ?)
                    WHERE cluster_id = ?
                    """,
                    (status.value, now, now, cluster_id),
                )
            else:
                conn.execute(
                    "UPDATE nengok_clusters SET status = ?, updated_at = ? WHERE cluster_id = ?",
                    (status.value, now, cluster_id),
                )

    def list_clusters(self, *, status: ClusterStatus | None = None) -> list[dict]:
        query = "SELECT * FROM nengok_clusters"
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY updated_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def record_approval(
        self,
        *,
        cluster_id: str,
        decision: str,
        reviewer: str | None,
        reason: str | None,
        source: str = "dashboard",
    ) -> str:
        approval_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO nengok_approvals
                  (approval_id, cluster_id, decision, reviewer, created_at, reason, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (approval_id, cluster_id, decision, reviewer, now, reason, source),
            )
        return approval_id

    def list_approvals(self, *, limit: int = 50, before: str | None = None) -> list[dict]:
        """
        Return approvals across all clusters, newest first.

        `before` is a cursor: the `approval_id` returned at the end of
        the previous page. Pagination is keyset-style (created_at DESC,
        approval_id DESC) so concurrent inserts cannot duplicate or
        drop rows between requests.
        """
        sql = """
            SELECT approval_id, cluster_id, decision, reviewer, reason, source, created_at
            FROM nengok_approvals
        """
        params: tuple = ()
        if before is not None:
            sql += """
                WHERE (created_at, approval_id) < (
                    SELECT created_at, approval_id FROM nengok_approvals WHERE approval_id = ?
                )
            """
            params = (before,)
        sql += " ORDER BY created_at DESC, approval_id DESC LIMIT ?"
        params = (*params, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_cluster_approvals(self, cluster_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT approval_id, cluster_id, decision, reviewer, reason, source, created_at
                FROM nengok_approvals
                WHERE cluster_id = ?
                ORDER BY created_at DESC, approval_id DESC
                """,
                (cluster_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_clusters_between(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict]:
        """Return clusters whose `created_at` falls inside the half-open `[since, until)` window."""
        sql, params = _range_sql(
            "SELECT * FROM nengok_clusters",
            column="created_at",
            since=since,
            until=until,
            order_by="created_at ASC, cluster_id ASC",
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_approvals_between(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict]:
        sql, params = _range_sql(
            "SELECT approval_id, cluster_id, decision, reviewer, reason, source, created_at "
            "FROM nengok_approvals",
            column="created_at",
            since=since,
            until=until,
            order_by="created_at ASC, approval_id ASC",
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_experiments_between(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict]:
        sql, params = _range_sql(
            """
            SELECT experiment_id, cluster_id, experiment_name, dataset_name,
                   baseline_pass_rate, fix_pass_rate,
                   golden_baseline_pass_rate, golden_fix_pass_rate,
                   per_case_json, created_at
            FROM nengok_experiments
            """,
            column="created_at",
            since=since,
            until=until,
            order_by="created_at ASC, row_id ASC",
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_cycles_between(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> list[dict]:
        sql, params = _range_sql(
            """
            SELECT cycle_id, started_at, ended_at, status,
                   clusters_processed, clusters_discovered,
                   gemini_tokens, gemini_dollars, error_message
            FROM nengok_cycles
            """,
            column="started_at",
            since=since,
            until=until,
            order_by="started_at ASC, cycle_id ASC",
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_recent_cycles(self, *, limit: int = 10) -> list[dict]:
        """Return the most recent cycle rows, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT cycle_id, started_at, ended_at, status,
                       clusters_processed, clusters_discovered,
                       gemini_tokens, gemini_dollars, error_message
                FROM nengok_cycles
                ORDER BY started_at DESC, cycle_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_cycle(self, record: CycleRecord) -> None:
        """Persist one cycle's outcome and Gemini spend for the overview dashboard."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO nengok_cycles
                  (cycle_id, started_at, ended_at, status,
                   clusters_processed, clusters_discovered,
                   gemini_tokens, gemini_dollars, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cycle_id) DO UPDATE SET
                    ended_at = excluded.ended_at,
                    status = excluded.status,
                    clusters_processed = excluded.clusters_processed,
                    clusters_discovered = excluded.clusters_discovered,
                    gemini_tokens = excluded.gemini_tokens,
                    gemini_dollars = excluded.gemini_dollars,
                    error_message = excluded.error_message
                """,
                (
                    record.cycle_id,
                    record.started_at.isoformat(),
                    record.ended_at.isoformat(),
                    record.status.value,
                    record.clusters_processed,
                    record.clusters_discovered,
                    record.gemini_tokens,
                    record.gemini_dollars,
                    record.error_message,
                ),
            )

    def record_experiment(self, *, cluster_id: str, result: ExperimentResult) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO nengok_experiments
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
                "SELECT status, COUNT(*) AS n FROM nengok_clusters GROUP BY status"
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
                FROM nengok_clusters
                WHERE first_seen IS NOT NULL AND diagnosed_at IS NOT NULL
                """
            ).fetchone()
            mttr_row = conn.execute(
                """
                SELECT AVG(
                    (julianday(a.created_at) - julianday(c.diagnosed_at)) * 86400.0
                ) AS seconds
                FROM nengok_clusters c
                JOIN nengok_approvals a ON a.cluster_id = c.cluster_id
                WHERE a.decision = 'approved' AND c.diagnosed_at IS NOT NULL
                """
            ).fetchone()

            regression_row = conn.execute(
                """
                SELECT COALESCE(SUM(json_array_length(per_case_json)), 0) AS total
                FROM nengok_experiments
                WHERE row_id IN (
                    SELECT MAX(row_id) FROM nengok_experiments GROUP BY cluster_id
                )
                """
            ).fetchone()

            pass_row = conn.execute(
                """
                SELECT AVG(fix_pass_rate) AS pass_rate
                FROM nengok_experiments
                WHERE created_at >= datetime('now', '-30 days')
                """
            ).fetchone()

            spend_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(gemini_tokens), 0) AS tokens,
                    COALESCE(SUM(gemini_dollars), 0.0) AS dollars
                FROM nengok_cycles
                WHERE started_at >= datetime('now', '-30 days')
                """
            ).fetchone()

            sparkline_rows = conn.execute(
                """
                SELECT
                    DATE(started_at) AS day,
                    COALESCE(SUM(gemini_tokens), 0) AS tokens,
                    COALESCE(SUM(gemini_dollars), 0.0) AS dollars
                FROM nengok_cycles
                WHERE started_at >= datetime('now', '-30 days')
                GROUP BY DATE(started_at)
                ORDER BY day ASC
                """
            ).fetchall()

            recent_cycle_rows = conn.execute(
                """
                SELECT cycle_id, started_at, ended_at, status,
                       clusters_processed, clusters_discovered,
                       gemini_tokens, gemini_dollars, error_message
                FROM nengok_cycles
                ORDER BY started_at DESC, cycle_id DESC
                LIMIT 10
                """
            ).fetchall()

        recent_cycles = [
            {
                "cycle_id": row["cycle_id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "status": row["status"] or "ok",
                "clusters_processed": int(row["clusters_processed"] or 0),
                "clusters_discovered": int(row["clusters_discovered"] or 0),
                "gemini_tokens": int(row["gemini_tokens"] or 0),
                "gemini_dollars": float(row["gemini_dollars"] or 0.0),
                "error_message": row["error_message"],
            }
            for row in recent_cycle_rows
        ]
        recent_status_counts: dict[str, int] = {}
        for row in recent_cycle_rows:
            key = row["status"] or "ok"
            recent_status_counts[key] = recent_status_counts.get(key, 0) + 1

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
            "gemini_tokens_used_30d": int(spend_row["tokens"] or 0),
            "gemini_dollars_used_30d": float(spend_row["dollars"] or 0.0),
            "gemini_spend_sparkline_30d": [
                {
                    "day": row["day"],
                    "tokens": int(row["tokens"] or 0),
                    "dollars": float(row["dollars"] or 0.0),
                }
                for row in sparkline_rows
            ],
            "recent_cycles": recent_cycles,
            "recent_cycle_status_counts": recent_status_counts,
        }

    def latest_experiment(self, cluster_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT experiment_id, cluster_id, experiment_name, dataset_name,
                       baseline_pass_rate, fix_pass_rate,
                       golden_baseline_pass_rate, golden_fix_pass_rate,
                       per_case_json, created_at
                FROM nengok_experiments
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
