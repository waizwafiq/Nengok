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

LEGACY_SCHEMA_VERSIONS_TABLE = "schema_versions"
LEGACY_VERSION_TO_REVISION: dict[int, str] = {
    1: "0001_initial_schema",
    2: "0002_rename_approval_columns",
    3: "0003_extend_cycle_history",
}


def build_config(engine: Engine) -> Config:
    """Return an Alembic `Config` bound to `engine` for in-process runs."""
    cfg = Config(str(ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    cfg.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False),
    )
    cfg.attributes["connection"] = engine
    return cfg


def upgrade_head(engine: Engine) -> None:
    """
    Apply every pending revision up to `head`.

    A database stamped by the pre-Alembic migrator (the `schema_versions`
    table from Phase 9.1) is converted in place: the highest applied
    legacy version maps to its Alembic counterpart, the database is
    stamped at that revision, and `schema_versions` is dropped. The
    later prefix-rename revision then runs as part of the normal
    upgrade and the operator never sees a "table already exists" error.
    """
    _stamp_legacy_history(engine)
    command.upgrade(build_config(engine), "head")


def _stamp_legacy_history(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if LEGACY_SCHEMA_VERSIONS_TABLE not in table_names:
        return
    if "alembic_version" in table_names:
        return

    with engine.connect() as connection:
        row = connection.execute(text("SELECT MAX(version) AS v FROM schema_versions")).fetchone()
    if row is None or row.v is None:
        return

    revision = LEGACY_VERSION_TO_REVISION.get(int(row.v))
    if revision is None:
        return

    command.stamp(build_config(engine), revision)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE schema_versions"))


def current_revision(engine: Engine) -> str | None:
    """Return the revision currently stamped on `engine`, or None."""
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"version_table": NENGOK_ALEMBIC_VERSION_TABLE},
        )
        return context.get_current_revision()


def script_directory(engine: Engine) -> ScriptDirectory:
    """Return the Alembic `ScriptDirectory` for the packaged revisions."""
    return ScriptDirectory.from_config(build_config(engine))
