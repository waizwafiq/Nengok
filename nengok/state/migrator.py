"""
Versioned SQL migrator for the local state database.

Each migration is a `NNNN_<name>.sql` file in `nengok/state/migrations/`.
On startup we discover every file in numeric order, compare against the
`schema_versions` bookkeeping table, and apply only the unapplied ones
inside a single transaction. Applied migrations are immutable: if a
file's sha256 changes after it has been recorded, startup refuses with
a copy-paste fix message that names the next free version number.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from nengok.utils.logging import get_logger

logger = get_logger(__name__)


_VERSION_PATTERN = re.compile(r"^(\d{4})_[A-Za-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """Raised when a migration file is malformed or has drifted from its applied copy."""


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    applied_at: str
    checksum: str


def discover_migrations(source: Traversable | Path) -> list[Migration]:
    """
    Return every migration in `source` sorted by numeric version.

    `source` is either an `importlib.resources.Traversable` (the
    packaged location) or a `Path` (used by the test suite to inject
    a temporary migrations directory).
    """
    found: list[Migration] = []
    seen_versions: set[int] = set()
    for entry in sorted(_iter_filenames(source)):
        match = _VERSION_PATTERN.match(entry)
        if not match:
            raise MigrationError(f"Migration filename '{entry}' does not match the NNNN_<name>.sql pattern.")
        version = int(match.group(1))
        if version in seen_versions:
            raise MigrationError(f"Duplicate migration version {version:04d}: '{entry}'.")
        seen_versions.add(version)
        sql = _read_text(source, entry)
        found.append(Migration(version=version, filename=entry, sql=sql))
    return sorted(found, key=lambda m: m.version)


def packaged_migrations_source() -> Traversable:
    return resources.files("nengok.state").joinpath("migrations")


def applied_migrations(conn: sqlite3.Connection) -> list[AppliedMigration]:
    _ensure_versions_table(conn)
    rows = conn.execute(
        "SELECT version, applied_at, checksum FROM schema_versions ORDER BY version ASC"
    ).fetchall()
    return [
        AppliedMigration(version=row["version"], applied_at=row["applied_at"], checksum=row["checksum"])
        for row in rows
    ]


def apply_pending(conn: sqlite3.Connection, migrations: list[Migration]) -> list[Migration]:
    """
    Apply every migration that has not yet been recorded.

    Verifies each already-applied migration's checksum first and raises
    `MigrationError` on drift. Each unapplied migration runs as a single
    `executescript` call; SQLite rolls back the partial DDL when the
    enclosing transaction errors out, so a broken file leaves the
    database untouched.
    """
    _ensure_versions_table(conn)
    applied = {row.version: row for row in applied_migrations(conn)}
    available_versions = {m.version for m in migrations}

    for version, record in applied.items():
        if version not in available_versions:
            raise MigrationError(
                f"Migration {version:04d} was applied on {record.applied_at} but is missing from "
                "the migrations directory. Restore the file or rebuild the database."
            )

    for migration in migrations:
        if migration.version not in applied:
            continue
        stored = applied[migration.version]
        if stored.checksum != migration.checksum:
            next_version = _next_free_version(applied=applied, available=available_versions)
            raise MigrationError(
                f"Migration {migration.filename} checksum changed since it was applied "
                f"(was {stored.checksum[:7]}, now {migration.checksum[:7]}). Migrations are "
                "immutable once applied. Either revert your changes to "
                f"{migration.filename} or create {next_version:04d}_<your_change>.sql with "
                "the new changes."
            )

    pending = [m for m in migrations if m.version not in applied]
    if not pending:
        return []

    now = datetime.now(UTC).isoformat()
    for migration in pending:
        logger.info("Applying migration %s", migration.filename)
        _apply_atomically(conn, migration=migration, applied_at=now)
    return pending


def _apply_atomically(conn: sqlite3.Connection, *, migration: Migration, applied_at: str) -> None:
    """
    Run one migration's DDL plus its `schema_versions` row inside one transaction.

    `executescript` implicitly commits any open transaction first and
    forbids parameter binding, so we split the migration body into
    statements ourselves and drive each through `conn.execute()`. That
    keeps the schema_versions INSERT parameterized and lets the
    surrounding explicit `BEGIN`/`COMMIT` cover the whole apply.
    """
    statements = _split_statements(migration.sql)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        for stmt in statements:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_versions (version, applied_at, checksum) VALUES (?, ?, ?)",
            (migration.version, applied_at, migration.checksum),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise


_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _split_statements(sql: str) -> list[str]:
    """
    Split a SQL script into individual statements safe for `conn.execute()`.

    Strips line and block comments, then splits on top-level semicolons
    that are not inside single- or double-quoted string literals. The
    inputs are migration files we author, so this does not need to
    handle every SQL dialect quirk, only the ones our migrations use.
    """
    stripped = _BLOCK_COMMENT.sub("", _LINE_COMMENT.sub("", sql))
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for ch in stripped:
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif ch == ";" and not in_single and not in_double:
            piece = "".join(current).strip()
            if piece:
                statements.append(piece)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def verify_checksums(conn: sqlite3.Connection, migrations: list[Migration]) -> list[Migration]:
    """Return the list of applied migrations whose checksum no longer matches the on-disk file."""
    drifted: list[Migration] = []
    applied = {row.version: row for row in applied_migrations(conn)}
    by_version = {m.version: m for m in migrations}
    for version, record in applied.items():
        migration = by_version.get(version)
        if migration is None:
            continue
        if migration.checksum != record.checksum:
            drifted.append(migration)
    return drifted


def _ensure_versions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            checksum   TEXT NOT NULL
        )
        """
    )


def _next_free_version(*, applied: dict[int, AppliedMigration], available: set[int]) -> int:
    used = set(applied) | available
    candidate = max(used) + 1 if used else 1
    return candidate


def _iter_filenames(source: Traversable | Path) -> Iterator[str]:
    if isinstance(source, Path):
        if not source.exists():
            return
        for path_child in source.iterdir():
            if path_child.is_file() and path_child.suffix == ".sql":
                yield path_child.name
        return
    for resource_child in source.iterdir():
        if resource_child.is_file() and resource_child.name.endswith(".sql"):
            yield resource_child.name


def _read_text(source: Traversable | Path, name: str) -> str:
    if isinstance(source, Path):
        return (source / name).read_text(encoding="utf-8")
    return source.joinpath(name).read_text(encoding="utf-8")
