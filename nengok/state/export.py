"""
Build a deterministic audit-export bundle from the local state database.

The JSON shape produced by `build_bundle` plus `serialize_json` is the
contract `docs/audit-export.md` documents and the seed for the v1.0
EU AI Act audit bundle (proposal section 12.6). Field renames and
removals are forbidden once shipped; additions land at the end of
their section.

CSV serialization is intentionally narrow: two sections, `clusters`
and `approvals`, separated by a `# <section>` line so a reviewer can
paste each block into a spreadsheet without surgery.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nengok import __version__
from nengok.state.store import StateStore

EXPORT_VERSION = 1

_DATE_FORMAT = "%Y-%m-%d"


class ExportDateError(ValueError):
    """Raised when a `--since` / `--until` value cannot be parsed."""


@dataclass(frozen=True)
class ExportFilter:
    since: datetime | None
    until: datetime | None

    @property
    def since_date(self) -> str | None:
        return self.since.date().isoformat() if self.since else None

    @property
    def until_date(self) -> str | None:
        return self.until.date().isoformat() if self.until else None


@dataclass
class ExportBundle:
    nengok_version: str
    generated_at: datetime
    filter: ExportFilter
    clusters: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    experiments: list[dict] = field(default_factory=list)
    cycles: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)


def parse_date_argument(value: str | None, *, kind: str) -> datetime | None:
    """Convert a `YYYY-MM-DD` CLI flag into a UTC datetime at midnight."""
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, _DATE_FORMAT)
    except ValueError as exc:
        raise ExportDateError(
            f"--{kind} expects YYYY-MM-DD (got '{value}'). Example: --{kind} 2026-01-01."
        ) from exc
    return parsed.replace(tzinfo=UTC)


def normalize_window(
    since: datetime | None, until: datetime | None
) -> tuple[datetime | None, datetime | None]:
    """
    Return a `[since, until)` half-open window that includes every row on `until`.

    `since` is treated as start-of-day UTC and `until` is shifted to the
    start of the day AFTER the operator-supplied date so the printed
    interval `--since 2026-01-01 --until 2026-01-31` covers the whole
    of 31 January without forcing the operator to think about end-of-day
    timestamps.
    """
    if since is not None and until is not None and until < since:
        raise ExportDateError(
            f"--until ({until.date().isoformat()}) precedes --since ({since.date().isoformat()})."
        )
    inclusive_until = until + timedelta(days=1) if until is not None else None
    return since, inclusive_until


def build_bundle(
    *,
    store: StateStore,
    artifacts_dir: Path,
    since: datetime | None = None,
    until: datetime | None = None,
    now: datetime | None = None,
) -> ExportBundle:
    """Collect every audit-relevant row whose timestamp falls inside the window."""
    window_start, window_end = normalize_window(since, until)

    clusters = store.list_clusters_between(since=window_start, until=window_end)
    approvals = store.list_approvals_between(since=window_start, until=window_end)
    experiments = store.list_experiments_between(since=window_start, until=window_end)
    cycles = store.list_cycles_between(since=window_start, until=window_end)

    artifact_pointers = collect_artifact_pointers(
        artifacts_dir=artifacts_dir,
        cluster_ids=[row["cluster_id"] for row in clusters],
    )

    return ExportBundle(
        nengok_version=__version__,
        generated_at=now or datetime.now(UTC),
        filter=ExportFilter(since=since, until=until),
        clusters=[_serialize_cluster_row(row) for row in clusters],
        approvals=[_serialize_approval_row(row) for row in approvals],
        experiments=[_serialize_experiment_row(row) for row in experiments],
        cycles=[_serialize_cycle_row(row) for row in cycles],
        artifacts=artifact_pointers,
    )


def collect_artifact_pointers(*, artifacts_dir: Path, cluster_ids: list[str]) -> list[dict]:
    """
    Inventory `artifacts/<cluster_id>/` for each cluster in the window.

    Records the relative directory, every regular file inside it with
    its size and sha256, and `null` for the directory when the bundle
    has never been written. Hashing the bytes lets a downstream auditor
    detect post-export tampering without re-reading the artifact content.
    """
    out: list[dict] = []
    for cluster_id in cluster_ids:
        cluster_dir = artifacts_dir / cluster_id
        if not cluster_dir.exists() or not cluster_dir.is_dir():
            out.append(
                {
                    "cluster_id": cluster_id,
                    "directory": None,
                    "files": [],
                }
            )
            continue
        files: list[dict] = []
        for path in sorted(cluster_dir.rglob("*")):
            if not path.is_file():
                continue
            files.append(
                {
                    "name": path.relative_to(cluster_dir).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
        out.append(
            {
                "cluster_id": cluster_id,
                "directory": _as_posix(cluster_dir),
                "files": files,
            }
        )
    return out


def serialize_json(bundle: ExportBundle, *, indent: int | None = 2) -> str:
    """Render the bundle as the documented JSON shape."""
    payload: dict[str, Any] = {
        "export_version": EXPORT_VERSION,
        "nengok_version": bundle.nengok_version,
        "generated_at": bundle.generated_at.isoformat(),
        "filter": {
            "since": bundle.filter.since_date,
            "until": bundle.filter.until_date,
        },
        "counts": {
            "clusters": len(bundle.clusters),
            "approvals": len(bundle.approvals),
            "experiments": len(bundle.experiments),
            "cycles": len(bundle.cycles),
            "artifacts": len(bundle.artifacts),
        },
        "clusters": bundle.clusters,
        "approvals": bundle.approvals,
        "experiments": bundle.experiments,
        "cycles": bundle.cycles,
        "artifacts": bundle.artifacts,
    }
    return json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=False)


_CLUSTER_CSV_FIELDS = (
    "cluster_id",
    "name",
    "description",
    "status",
    "created_at",
    "updated_at",
    "first_seen",
    "diagnosed_at",
    "member_span_count",
)

_APPROVAL_CSV_FIELDS = (
    "approval_id",
    "cluster_id",
    "decision",
    "reviewer",
    "reason",
    "created_at",
)


def serialize_csv(bundle: ExportBundle) -> str:
    """
    Emit `clusters` and `approvals` as two header-prefixed CSV sections.

    Each section starts with a `# clusters` or `# approvals` marker on
    its own line so a spreadsheet user can split the file by the marker
    or strip the markers and import the rest as a single table per file.
    """
    out = io.StringIO()
    out.write("# clusters\n")
    writer = csv.DictWriter(out, fieldnames=_CLUSTER_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in bundle.clusters:
        writer.writerow(
            {
                "cluster_id": row.get("cluster_id", ""),
                "name": row.get("name", ""),
                "description": row.get("description", "") or "",
                "status": row.get("status", ""),
                "created_at": row.get("created_at", ""),
                "updated_at": row.get("updated_at", ""),
                "first_seen": row.get("first_seen") or "",
                "diagnosed_at": row.get("diagnosed_at") or "",
                "member_span_count": len(row.get("member_span_ids", []) or []),
            }
        )
    out.write("\n# approvals\n")
    writer = csv.DictWriter(out, fieldnames=_APPROVAL_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in bundle.approvals:
        writer.writerow(
            {
                "approval_id": row.get("approval_id", ""),
                "cluster_id": row.get("cluster_id", ""),
                "decision": row.get("decision", ""),
                "reviewer": row.get("reviewer") or "",
                "reason": row.get("reason") or "",
                "created_at": row.get("created_at", ""),
            }
        )
    return out.getvalue()


def _serialize_cluster_row(row: dict) -> dict:
    member_spans = _maybe_json_list(row.get("member_spans_json"))
    hypothesis = _maybe_json_object(row.get("hypothesis_json"))
    return {
        "cluster_id": row["cluster_id"],
        "name": row["name"],
        "description": row.get("description"),
        "status": row["status"],
        "hypothesis": hypothesis,
        "member_span_ids": member_spans,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "first_seen": row.get("first_seen"),
        "diagnosed_at": row.get("diagnosed_at"),
    }


def _serialize_approval_row(row: dict) -> dict:
    return {
        "approval_id": row["approval_id"],
        "cluster_id": row["cluster_id"],
        "decision": row["decision"],
        "reviewer": row.get("reviewer"),
        "reason": row.get("reason"),
        "created_at": row["created_at"],
    }


def _serialize_experiment_row(row: dict) -> dict:
    per_case = _maybe_json_list(row.get("per_case_json"))
    return {
        "experiment_id": row.get("experiment_id"),
        "cluster_id": row["cluster_id"],
        "experiment_name": row["experiment_name"],
        "dataset_name": row["dataset_name"],
        "baseline_pass_rate": row["baseline_pass_rate"],
        "fix_pass_rate": row["fix_pass_rate"],
        "golden_baseline_pass_rate": row["golden_baseline_pass_rate"],
        "golden_fix_pass_rate": row["golden_fix_pass_rate"],
        "per_case": per_case,
        "created_at": row["created_at"],
    }


def _serialize_cycle_row(row: dict) -> dict:
    return {
        "cycle_id": row["cycle_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "gemini_tokens": int(row.get("gemini_tokens") or 0),
        "gemini_dollars": float(row.get("gemini_dollars") or 0.0),
        "status": row.get("status") or "ok",
        "clusters_processed": int(row.get("clusters_processed") or 0),
        "clusters_discovered": int(row.get("clusters_discovered") or 0),
        "error_message": row.get("error_message"),
    }


def _maybe_json_list(raw: Any) -> list:
    if not raw:
        return []
    decoded = json.loads(raw)
    if not isinstance(decoded, list):
        raise ValueError(f"Expected JSON array, got {type(decoded).__name__}")
    return decoded


def _maybe_json_object(raw: Any) -> dict | None:
    if not raw:
        return None
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError(f"Expected JSON object, got {type(decoded).__name__}")
    return decoded


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_posix(path: Path) -> str:
    """Return a forward-slash path so JSON output stays portable across OSes."""
    return path.as_posix()
