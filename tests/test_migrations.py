"""Coverage for `nengok.state.migrator` and the `nengok db` subcommands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nengok import cli as cli_module
from nengok.cli import app
from nengok.config import NengokConfig
from nengok.state.migrator import (
    MigrationError,
    applied_migrations,
    apply_pending,
    discover_migrations,
    verify_checksums,
)
from nengok.state.store import StateStore

INITIAL_SQL = """
CREATE TABLE widgets (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
"""

SECOND_SQL = """
ALTER TABLE widgets ADD COLUMN color TEXT;
"""

BROKEN_SQL = """
ALTER TABLE widgets ADD COLUMN size TEXT;
CREATE TABLE widgets (id INTEGER);
"""


def _write(directory: Path, filename: str, body: str) -> None:
    (directory / filename).write_text(body, encoding="utf-8")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


def test_discover_orders_by_version(migrations_dir: Path) -> None:
    _write(migrations_dir, "0002_second.sql", "SELECT 2;")
    _write(migrations_dir, "0001_first.sql", "SELECT 1;")

    discovered = discover_migrations(migrations_dir)

    assert [m.version for m in discovered] == [1, 2]
    assert discovered[0].filename == "0001_first.sql"


def test_discover_rejects_malformed_filename(migrations_dir: Path) -> None:
    _write(migrations_dir, "001_too_short.sql", "SELECT 1;")
    with pytest.raises(MigrationError, match="does not match the NNNN_<name>.sql pattern"):
        discover_migrations(migrations_dir)


def test_apply_pending_runs_all_migrations_on_fresh_db(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    _write(migrations_dir, "0002_second.sql", SECOND_SQL)

    db_path = tmp_path / "state.db"
    conn = _connect(db_path)
    try:
        applied = apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    assert [m.version for m in applied] == [1, 2]

    conn = _connect(db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(widgets)").fetchall()}
        records = applied_migrations(conn)
    finally:
        conn.close()

    assert {"id", "name", "color"}.issubset(columns)
    assert [r.version for r in records] == [1, 2]


def test_apply_pending_is_noop_when_up_to_date(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)

    db_path = tmp_path / "state.db"
    conn = _connect(db_path)
    try:
        apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    conn = _connect(db_path)
    try:
        second_call = apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    assert second_call == []


def test_apply_pending_only_runs_new_migrations(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    db_path = tmp_path / "state.db"

    conn = _connect(db_path)
    try:
        apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    _write(migrations_dir, "0002_second.sql", SECOND_SQL)

    conn = _connect(db_path)
    try:
        applied = apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    assert [m.version for m in applied] == [2]


def test_checksum_drift_refuses_to_start(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    db_path = tmp_path / "state.db"

    conn = _connect(db_path)
    try:
        apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL + "\n-- mutated\n")

    conn = _connect(db_path)
    try:
        with pytest.raises(MigrationError, match="checksum changed since it was applied"):
            apply_pending(conn, discover_migrations(migrations_dir))
    finally:
        conn.close()


def test_drift_message_names_next_free_version(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    _write(migrations_dir, "0002_second.sql", SECOND_SQL)
    db_path = tmp_path / "state.db"

    conn = _connect(db_path)
    try:
        apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    _write(migrations_dir, "0002_second.sql", SECOND_SQL + "\n-- altered\n")

    conn = _connect(db_path)
    try:
        with pytest.raises(MigrationError, match="0003_<your_change>.sql"):
            apply_pending(conn, discover_migrations(migrations_dir))
    finally:
        conn.close()


def test_broken_sql_rolls_back_and_leaves_no_partial_state(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    _write(migrations_dir, "0002_broken.sql", BROKEN_SQL)
    db_path = tmp_path / "state.db"

    conn = _connect(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_pending(conn, discover_migrations(migrations_dir))
    finally:
        conn.close()

    conn = _connect(db_path)
    try:
        records = applied_migrations(conn)
        widget_columns = {row["name"] for row in conn.execute("PRAGMA table_info(widgets)").fetchall()}
    finally:
        conn.close()

    assert [r.version for r in records] == [1]
    assert "size" not in widget_columns
    assert {"id", "name"}.issubset(widget_columns)


def test_verify_checksums_returns_drifted_migrations(tmp_path: Path, migrations_dir: Path) -> None:
    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL)
    db_path = tmp_path / "state.db"

    conn = _connect(db_path)
    try:
        apply_pending(conn, discover_migrations(migrations_dir))
        conn.commit()
    finally:
        conn.close()

    _write(migrations_dir, "0001_initial.sql", INITIAL_SQL + "\n-- mutated\n")

    conn = _connect(db_path)
    try:
        drifted = verify_checksums(conn, discover_migrations(migrations_dir))
    finally:
        conn.close()

    assert [m.version for m in drifted] == [1]


def test_state_store_records_packaged_migrations(tmp_path: Path) -> None:
    StateStore(tmp_path / "state.db")
    conn = _connect(tmp_path / "state.db")
    try:
        records = applied_migrations(conn)
    finally:
        conn.close()
    assert [r.version for r in records] == [1, 2, 3]


def test_db_status_lists_applied_migrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    StateStore(tmp_path / "state.db")
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key="AIzaTEST-key-for-unit-tests",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["db", "status"])

    assert result.exit_code == 0, result.output
    assert "version" in result.output
    assert "1" in result.output


def test_db_check_passes_when_packaged_checksums_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    StateStore(tmp_path / "state.db")
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key="AIzaTEST-key-for-unit-tests",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    result = CliRunner().invoke(app, ["db", "check"])

    assert result.exit_code == 0, result.output
    assert "match their applied checksum" in result.output


def test_db_migrate_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = NengokConfig.load(
        config_path=tmp_path / "missing.toml",
        phoenix_base_url="http://localhost:6006",
        phoenix_api_key=None,
        google_api_key="AIzaTEST-key-for-unit-tests",
        artifacts_dir=tmp_path / "artifacts",
        state_db_path=tmp_path / "state.db",
    )
    monkeypatch.setattr(cli_module, "_load_config", lambda **_: config)
    cli_module._reset_startup_banner_for_tests()

    first = CliRunner().invoke(app, ["db", "migrate"])
    second = CliRunner().invoke(app, ["db", "migrate"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Applied 0001_initial.sql" in first.output
    assert "up to date" in second.output
