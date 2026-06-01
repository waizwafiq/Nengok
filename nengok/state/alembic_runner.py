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

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

ALEMBIC_INI_PATH: Path = Path(__file__).parent / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION: Path = Path(__file__).parent / "alembic"


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
    """Apply every pending revision up to `head`."""
    command.upgrade(build_config(engine), "head")


def current_revision(engine: Engine) -> str | None:
    """Return the revision currently stamped on `engine`, or None."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def script_directory(engine: Engine) -> ScriptDirectory:
    """Return the Alembic `ScriptDirectory` for the packaged revisions."""
    return ScriptDirectory.from_config(build_config(engine))
