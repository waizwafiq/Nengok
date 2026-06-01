"""Coverage for `nengok.state.export` and the `nengok export` CLI subcommand."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok import cli as cli_module
from nengok.cli import app
from nengok.config import NengokConfig
from nengok.core.types import (
    Cluster,
    ClusterStatus,
    CycleRecord,
    CycleStatus,
    ExperimentResult,
    RootCauseHypothesis,
)
from nengok.state.export import (
    EXPORT_VERSION,
    ExportDateError,
    build_bundle,
    collect_artifact_pointers,
    normalize_window,
    parse_date_argument,
    serialize_csv,
    serialize_json,
)
from nengok.state.store import StateStore


def _config(tmp_path: Path) -> NengokConfig:
    return NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        google_api_key="AIzaTEST",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )


def _seed_cluster(
    store: StateStore,
    cluster_id: str,
    *,
    created_at: datetime,
    member_spans: list[str] | None = None,
    hypothesis: RootCauseHypothesis | None = None,
    status: ClusterStatus = ClusterStatus.DIAGNOSED,
) -> None:
    store.upsert_cluster(
        Cluster(
            cluster_id=cluster_id,
            name=cluster_id,
            description=f"{cluster_id} desc",
            status=status,
            member_span_ids=member_spans or [],
            exemplar_span_ids=[],
            hypothesis=hypothesis,
            created_at=created_at,
            updated_at=created_at,
        ),
        first_seen=created_at,
    )


def _approve(
    store: StateStore,
    cluster_id: str,
    *,
    reviewer: str = "alice",
    reason: str = "ok",
    created_at: datetime | None = None,
) -> str:
    """Record an approval, optionally pinning created_at for window tests."""
    if created_at is None:
        return store.record_approval(
            cluster_id=cluster_id,
            decision="approved",
            reviewer=reviewer,
            reason=reason,
        )
    approval_id = str(uuid.uuid4())
    conn = sqlite3.connect(store._db_path)
    try:
        conn.execute(
            "INSERT INTO nengok_approvals"
            " (approval_id, cluster_id, decision, reviewer, created_at, reason)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (approval_id, cluster_id, "approved", reviewer, created_at.isoformat(), reason),
        )
        conn.commit()
    finally:
        conn.close()
    return approval_id


def _experiment(
    store: StateStore,
    cluster_id: str,
    *,
    pass_rate: float = 0.9,
    created_at: datetime | None = None,
) -> None:
    """Record an experiment, optionally pinning created_at for window tests."""
    if created_at is None:
        store.record_experiment(
            cluster_id=cluster_id,
            result=ExperimentResult(
                experiment_name=f"exp-{cluster_id}",
                experiment_id=f"e-{cluster_id}",
                dataset_name=f"ds-{cluster_id}",
                baseline_pass_rate=0.4,
                fix_pass_rate=pass_rate,
                golden_baseline_pass_rate=0.85,
                golden_fix_pass_rate=0.9,
                per_case=[{"case_id": "k1", "baseline": False, "fix": True}],
            ),
        )
        return
    conn = sqlite3.connect(store._db_path)
    try:
        conn.execute(
            "INSERT INTO nengok_experiments"
            " (experiment_id, cluster_id, experiment_name, dataset_name,"
            " baseline_pass_rate, fix_pass_rate, golden_baseline_pass_rate, golden_fix_pass_rate,"
            " per_case_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"e-{cluster_id}",
                cluster_id,
                f"exp-{cluster_id}",
                f"ds-{cluster_id}",
                0.4,
                pass_rate,
                0.85,
                0.9,
                json.dumps([{"case_id": "k1", "baseline": False, "fix": True}]),
                created_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _cycle(store: StateStore, cycle_id: str, *, started_at: datetime) -> None:
    store.record_cycle(
        CycleRecord(
            cycle_id=cycle_id,
            started_at=started_at,
            ended_at=started_at,
            status=CycleStatus.OK,
            gemini_tokens=100,
            gemini_dollars=0.5,
        )
    )


def test_parse_date_argument_returns_utc_midnight() -> None:
    parsed = parse_date_argument("2026-01-15", kind="since")
    assert parsed == datetime(2026, 1, 15, tzinfo=UTC)


def test_parse_date_argument_rejects_garbage() -> None:
    with pytest.raises(ExportDateError) as info:
        parse_date_argument("yesterday", kind="since")
    assert "YYYY-MM-DD" in str(info.value)


def test_normalize_window_makes_until_inclusive_of_named_day() -> None:
    since = parse_date_argument("2026-01-01", kind="since")
    until = parse_date_argument("2026-01-31", kind="until")
    start, end = normalize_window(since, until)
    assert start == datetime(2026, 1, 1, tzinfo=UTC)
    assert end == datetime(2026, 2, 1, tzinfo=UTC)


def test_normalize_window_rejects_until_before_since() -> None:
    since = parse_date_argument("2026-02-01", kind="since")
    until = parse_date_argument("2026-01-01", kind="until")
    with pytest.raises(ExportDateError):
        normalize_window(since, until)


def test_build_bundle_filters_by_window(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)

    inside = datetime(2026, 1, 15, 10, tzinfo=UTC)
    before = datetime(2025, 12, 1, tzinfo=UTC)
    after = datetime(2026, 3, 1, tzinfo=UTC)

    _seed_cluster(store, "c-inside", created_at=inside, member_spans=["s1", "s2"])
    _seed_cluster(store, "c-before", created_at=before)
    _seed_cluster(store, "c-after", created_at=after)
    _approve(store, "c-inside", created_at=inside)
    _approve(store, "c-after", created_at=after)
    _experiment(store, "c-inside", created_at=inside)
    _experiment(store, "c-after", created_at=after)
    _cycle(store, "cycle-inside", started_at=inside)
    _cycle(store, "cycle-after", started_at=after)

    since = parse_date_argument("2026-01-01", kind="since")
    until = parse_date_argument("2026-01-31", kind="until")
    bundle = build_bundle(
        store=store,
        artifacts_dir=config.artifacts_dir,
        since=since,
        until=until,
    )

    cluster_ids = [c["cluster_id"] for c in bundle.clusters]
    assert cluster_ids == ["c-inside"]
    assert [a["cluster_id"] for a in bundle.approvals] == ["c-inside"]
    assert [e["cluster_id"] for e in bundle.experiments] == ["c-inside"]
    assert [c["cycle_id"] for c in bundle.cycles] == ["cycle-inside"]
    assert bundle.filter.since_date == "2026-01-01"
    assert bundle.filter.until_date == "2026-01-31"


def test_build_bundle_returns_everything_when_no_window(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1", created_at=datetime(2025, 6, 1, tzinfo=UTC))
    _seed_cluster(store, "c-2", created_at=datetime(2026, 4, 1, tzinfo=UTC))

    bundle = build_bundle(store=store, artifacts_dir=config.artifacts_dir)

    assert {c["cluster_id"] for c in bundle.clusters} == {"c-1", "c-2"}


def test_serialize_json_payload_matches_documented_schema(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    when = datetime(2026, 2, 12, 10, 11, 12, tzinfo=UTC)
    hypothesis = RootCauseHypothesis(
        summary="missing units",
        expected_behavior="returns celsius",
        actual_behavior="returns fahrenheit",
        likely_cause="prompt ambiguity",
        implicated_tools=["weather"],
    )
    _seed_cluster(store, "c-1", created_at=when, member_spans=["s1"], hypothesis=hypothesis)
    _approve(store, "c-1")
    _experiment(store, "c-1")
    _cycle(store, "cycle-1", started_at=when)

    bundle = build_bundle(
        store=store,
        artifacts_dir=config.artifacts_dir,
        now=datetime(2026, 5, 27, 0, 0, tzinfo=UTC),
    )
    payload = json.loads(serialize_json(bundle))

    assert payload["export_version"] == EXPORT_VERSION
    assert payload["counts"] == {
        "clusters": 1,
        "approvals": 1,
        "experiments": 1,
        "cycles": 1,
        "artifacts": 1,
    }
    cluster = payload["clusters"][0]
    assert cluster["hypothesis"]["implicated_tools"] == ["weather"]
    assert cluster["member_span_ids"] == ["s1"]
    assert payload["approvals"][0]["decision"] == "approved"
    assert payload["experiments"][0]["per_case"][0]["case_id"] == "k1"
    assert payload["cycles"][0]["gemini_tokens"] == 100
    assert payload["artifacts"][0]["files"] == []
    assert payload["artifacts"][0]["directory"] is None


def test_collect_artifact_pointers_hashes_files(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    cluster_dir = artifacts_dir / "c-1"
    cluster_dir.mkdir(parents=True)
    (cluster_dir / "prompt.md").write_text("hello\n", encoding="utf-8")
    (cluster_dir / "rca.md").write_text("world\n", encoding="utf-8")

    pointers = collect_artifact_pointers(artifacts_dir=artifacts_dir, cluster_ids=["c-1", "c-missing"])

    assert len(pointers) == 2
    c1 = pointers[0]
    assert c1["cluster_id"] == "c-1"
    assert c1["directory"].endswith("artifacts/c-1")
    names = [f["name"] for f in c1["files"]]
    assert names == ["prompt.md", "rca.md"]
    for entry in c1["files"]:
        assert len(entry["sha256"]) == 64
        assert entry["size_bytes"] > 0
    missing = pointers[1]
    assert missing["directory"] is None
    assert missing["files"] == []


def test_serialize_csv_emits_two_sections(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    when = datetime(2026, 1, 15, tzinfo=UTC)
    _seed_cluster(store, "c-1", created_at=when, member_spans=["s1", "s2"])
    _approve(store, "c-1", reviewer="alice", reason="ok, ships")

    bundle = build_bundle(store=store, artifacts_dir=config.artifacts_dir)
    rendered = serialize_csv(bundle)

    assert rendered.startswith("# clusters\n")
    assert "\n# approvals\n" in rendered

    cluster_block, approval_block = rendered.split("\n# approvals\n", 1)
    cluster_block = cluster_block.removeprefix("# clusters\n")
    cluster_rows = list(csv.DictReader(io.StringIO(cluster_block)))
    approval_rows = list(csv.DictReader(io.StringIO(approval_block)))

    assert cluster_rows[0]["cluster_id"] == "c-1"
    assert cluster_rows[0]["member_span_count"] == "2"
    assert approval_rows[0]["reason"] == "ok, ships"


def test_cli_export_writes_json_to_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1", created_at=datetime(2026, 1, 15, tzinfo=UTC))
    _approve(store, "c-1")
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["export", "--since", "2026-01-01", "--until", "2026-01-31"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["counts"]["clusters"] == 1
    assert payload["filter"] == {"since": "2026-01-01", "until": "2026-01-31"}


def test_cli_export_writes_csv_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    store = StateStore(config.state_db_path)
    _seed_cluster(store, "c-1", created_at=datetime(2026, 1, 15, tzinfo=UTC))
    _approve(store, "c-1")
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    output_path = tmp_path / "out" / "audit.csv"
    result = CliRunner().invoke(
        app,
        ["export", "--format", "csv", "--output", str(output_path)],
    )

    assert result.exit_code == 0, result.output
    assert output_path.exists()
    body = output_path.read_text(encoding="utf-8")
    assert body.startswith("# clusters\n")
    assert "# approvals\n" in body


def test_cli_export_rejects_unknown_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    StateStore(config.state_db_path)
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["export", "--format", "xml"])

    assert result.exit_code == 2
    assert "Unknown --format" in result.output


def test_cli_export_errors_when_state_database_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["export"])

    assert result.exit_code == 2
    assert "No state database" in result.output


def test_cli_export_rejects_bad_date_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    StateStore(config.state_db_path)
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["export", "--since", "yesterday"])

    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output
