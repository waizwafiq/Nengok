"""
Run the Alembic migration suite across every supported dialect.

SQLite always runs (file-backed temp DB). Postgres and MySQL legs run
when their respective `NENGOK_TEST_POSTGRES_URL` / `NENGOK_TEST_MYSQL_URL`
environment variables point at a reachable instance. The Phase 14.5
matrix CI exports those vars from `services:` containers; locally,
developers can wire them up with the docker-compose files added in
Phase 14.4.

The contract is that the final `MetaData` fingerprint after `upgrade
head` matches across every dialect, so that store-layer code written
against one backend keeps working on the other two.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from nengok.state.alembic_runner import (
    LEGACY_VERSION_TO_REVISION,
    current_revision,
    script_directory,
    upgrade_head,
)

POSTGRES_ENV = "NENGOK_TEST_POSTGRES_URL"
MYSQL_ENV = "NENGOK_TEST_MYSQL_URL"

EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "nengok_clusters",
        "nengok_seen_spans",
        "nengok_approvals",
        "nengok_experiments",
        "nengok_cycles",
    }
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'state.db').as_posix()}"


def _maybe_url(env_var: str) -> str | None:
    url = os.environ.get(env_var)
    if not url:
        return None
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
    except OperationalError:
        return None
    return url


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(_sqlite_url(tmp_path))
    yield engine
    engine.dispose()


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    url = _maybe_url(POSTGRES_ENV)
    if url is None:
        pytest.skip(f"{POSTGRES_ENV} is not set or not reachable.")
    engine = create_engine(url)
    yield engine
    _drop_all_nengok(engine)
    engine.dispose()


@pytest.fixture
def mysql_engine() -> Iterator[Engine]:
    url = _maybe_url(MYSQL_ENV)
    if url is None:
        pytest.skip(f"{MYSQL_ENV} is not set or not reachable.")
    engine = create_engine(url)
    yield engine
    _drop_all_nengok(engine)
    engine.dispose()


def _drop_all_nengok(engine: Engine) -> None:
    inspector = inspect(engine)
    for name in inspector.get_table_names():
        if name == "alembic_version" or name.startswith("nengok_"):
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {name}"))


def _engine_fingerprint(engine: Engine) -> list[tuple[str, tuple[str, ...]]]:
    """
    Return (table, (column...)) tuples for every nengok-owned table.

    The list is sorted so two engines that reached head via the same
    revisions compare byte-for-byte. Column type is intentionally
    excluded: the dialect rewrites `Text` and `String` differently
    on each backend, and the Alembic op-set guarantees the logical
    type rather than the physical one.
    """
    inspector = inspect(engine)
    rows: list[tuple[str, tuple[str, ...]]] = []
    for table in sorted(inspector.get_table_names()):
        if not table.startswith("nengok_"):
            continue
        columns = tuple(sorted(col["name"] for col in inspector.get_columns(table)))
        rows.append((table, columns))
    return rows


def test_sqlite_upgrade_head_creates_prefixed_tables(sqlite_engine: Engine) -> None:
    upgrade_head(sqlite_engine)

    table_names = set(inspect(sqlite_engine).get_table_names())
    assert EXPECTED_TABLES.issubset(table_names)
    assert current_revision(sqlite_engine) == _packaged_head(sqlite_engine)


def test_sqlite_upgrade_head_is_idempotent(sqlite_engine: Engine) -> None:
    upgrade_head(sqlite_engine)
    first_fingerprint = _engine_fingerprint(sqlite_engine)
    upgrade_head(sqlite_engine)
    second_fingerprint = _engine_fingerprint(sqlite_engine)
    assert first_fingerprint == second_fingerprint


def test_legacy_schema_versions_database_is_stamped_and_renamed(tmp_path: Path) -> None:
    """A pre-Alembic SQLite file is stamped, then upgraded to the renamed schema."""
    db_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with legacy_engine.begin() as conn:
        conn.execute(text("CREATE TABLE clusters (cluster_id TEXT PRIMARY KEY, status TEXT)"))
        conn.execute(text("CREATE INDEX clusters_status_idx ON clusters (status)"))
        conn.execute(text("CREATE TABLE seen_spans (span_id TEXT PRIMARY KEY)"))
        conn.execute(
            text("CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, cluster_id TEXT, created_at TEXT)")
        )
        conn.execute(text("CREATE INDEX approvals_cluster_idx ON approvals (cluster_id)"))
        conn.execute(text("CREATE INDEX approvals_created_idx ON approvals (created_at)"))
        conn.execute(
            text("CREATE TABLE experiments (" "row_id INTEGER PRIMARY KEY, cluster_id TEXT, created_at TEXT)")
        )
        conn.execute(text("CREATE INDEX experiments_cluster_idx ON experiments (cluster_id)"))
        conn.execute(text("CREATE INDEX experiments_created_idx ON experiments (created_at)"))
        conn.execute(text("CREATE TABLE cycles (cycle_id TEXT PRIMARY KEY, started_at TEXT)"))
        conn.execute(text("CREATE INDEX cycles_started_idx ON cycles (started_at)"))
        conn.execute(
            text(
                "CREATE TABLE schema_versions ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
            )
        )
        for version in (1, 2, 3):
            conn.execute(
                text(
                    "INSERT INTO schema_versions (version, applied_at, checksum) "
                    "VALUES (:v, '2026-01-01T00:00:00+00:00', 'x')"
                ),
                {"v": version},
            )
    legacy_engine.dispose()

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    upgrade_head(engine)

    table_names = set(inspect(engine).get_table_names())
    assert "schema_versions" not in table_names
    assert EXPECTED_TABLES.issubset(table_names)
    assert "clusters" not in table_names
    engine.dispose()


def test_legacy_revision_mapping_is_complete() -> None:
    """Every legacy version maps to a real Alembic revision."""
    for version in (1, 2, 3):
        assert version in LEGACY_VERSION_TO_REVISION


def test_postgres_upgrade_head_matches_sqlite_fingerprint(
    sqlite_engine: Engine, postgres_engine: Engine
) -> None:
    upgrade_head(sqlite_engine)
    upgrade_head(postgres_engine)
    assert _engine_fingerprint(postgres_engine) == _engine_fingerprint(sqlite_engine)


def test_mysql_upgrade_head_matches_sqlite_fingerprint(sqlite_engine: Engine, mysql_engine: Engine) -> None:
    upgrade_head(sqlite_engine)
    upgrade_head(mysql_engine)
    assert _engine_fingerprint(mysql_engine) == _engine_fingerprint(sqlite_engine)


def _packaged_head(engine: Engine) -> str | None:
    return script_directory(engine).get_current_head()
