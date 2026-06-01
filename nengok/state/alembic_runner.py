"""
Programmatic wrappers around `alembic.command` for the Nengok CLI.

The state store and the `nengok db` subcommands both need to drive
Alembic from inside the process. This module hides the boilerplate of
locating `alembic.ini`, pointing the script directory at the packaged
`alembic/` folder, and binding a live SQLAlchemy connection to the
`env.py` runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

ALEMBIC_INI_PATH: Path = Path(__file__).parent / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION: Path = Path(__file__).parent / "alembic"

NENGOK_ALEMBIC_VERSION_TABLE = "nengok_alembic_version"
DEFAULT_ALEMBIC_VERSION_TABLE = "alembic_version"

KNOWN_NENGOK_REVISIONS: frozenset[str] = frozenset(
    {
        "0001_initial_schema",
        "0002_rename_approval_columns",
        "0003_extend_cycle_history",
        "0004_prefix_tables_with_nengok",
    }
)

LEGACY_SCHEMA_VERSIONS_TABLE = "schema_versions"
LEGACY_VERSION_TO_REVISION: dict[int, str] = {
    1: "0001_initial_schema",
    2: "0002_rename_approval_columns",
    3: "0003_extend_cycle_history",
}


def build_config(engine: Engine, *, schema: str | None = None) -> Config:
    """Return an Alembic `Config` bound to `engine` for in-process runs."""
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    cfg.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False),
    )
    cfg.attributes["connection"] = engine
    if schema is not None:
        cfg.attributes["version_table_schema"] = schema
    return cfg


def upgrade_head(engine: Engine, *, schema: str | None = None) -> None:
    """
    Apply every pending revision up to `head`.

    A database stamped by the pre-Alembic migrator (the `schema_versions`
    table from Phase 9.1) is converted in place: the highest applied
    legacy version maps to its Alembic counterpart, the database is
    stamped at that revision, and `schema_versions` is dropped. The
    later prefix-rename revision then runs as part of the normal
    upgrade and the operator never sees a "table already exists" error.

    A database stamped by a previous Nengok install at the default
    `alembic_version` table is reconciled into `nengok_alembic_version`
    when every row references a packaged Nengok revision id. An
    `alembic_version` table whose rows reference an unknown revision
    belongs to the operator's own Alembic environment and is left in
    place untouched.
    """
    _stamp_legacy_history(engine, schema=schema)
    _reconcile_legacy_alembic_version(engine)
    command.upgrade(build_config(engine, schema=schema), "head")


def _reconcile_legacy_alembic_version(engine: Engine) -> None:
    """
    Copy a previous-install `alembic_version` into `nengok_alembic_version`.

    Older Nengok installs wrote revision rows to Alembic's default
    bookkeeping table, which collides with any other Alembic-driven
    application sharing the database. When a default-named table is
    present and every revision id it carries belongs to the packaged
    Nengok history, the rows are copied to the namespaced table and
    the default-named table is dropped. When even one row references
    an unknown revision id, the table belongs to the operator's own
    Alembic environment and Nengok leaves it alone.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if DEFAULT_ALEMBIC_VERSION_TABLE not in table_names:
        return
    if NENGOK_ALEMBIC_VERSION_TABLE in table_names:
        return

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).fetchall()

    if not rows:
        return

    revision_ids = {row.version_num for row in rows}
    if not revision_ids.issubset(KNOWN_NENGOK_REVISIONS):
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE nengok_alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT nengok_alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        for revision_id in revision_ids:
            connection.execute(
                text("INSERT INTO nengok_alembic_version (version_num) VALUES (:rev)"),
                {"rev": revision_id},
            )
        connection.execute(text("DROP TABLE alembic_version"))


def _stamp_legacy_history(engine: Engine, *, schema: str | None = None) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if LEGACY_SCHEMA_VERSIONS_TABLE not in table_names:
        return
    if DEFAULT_ALEMBIC_VERSION_TABLE in table_names or NENGOK_ALEMBIC_VERSION_TABLE in table_names:
        return

    with engine.connect() as connection:
        row = connection.execute(text("SELECT MAX(version) AS v FROM schema_versions")).fetchone()
    if row is None or row.v is None:
        return

    revision = LEGACY_VERSION_TO_REVISION.get(int(row.v))
    if revision is None:
        return

    command.stamp(build_config(engine, schema=schema), revision)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE schema_versions"))


def current_revision(engine: Engine, *, schema: str | None = None) -> str | None:
    """Return the revision currently stamped on `engine`, or None."""
    opts: dict[str, str] = {"version_table": NENGOK_ALEMBIC_VERSION_TABLE}
    if schema is not None:
        opts["version_table_schema"] = schema
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts=opts)
        return context.get_current_revision()


def script_directory(engine: Engine) -> ScriptDirectory:
    """Return the Alembic `ScriptDirectory` for the packaged revisions."""
    return ScriptDirectory.from_config(build_config(engine))
