"""
Alembic environment for Nengok's state store.

Runs both online (against a live engine) and offline (emits SQL). The
engine is sourced from one of two places, in order:

  1. `config.attributes["connection"]` injected by code that already
     built a SQLAlchemy engine (the in-process path used by
     `StateStore` and the `nengok db` CLI).
  2. `sqlalchemy.url` set on the Alembic `Config` object before
     `command.upgrade(...)` is called.

There is no autogenerate support and no shared `target_metadata`: every
revision authors its own `op.create_table(...)` / `op.alter_column(...)`
calls so the history is explicit and dialect-portable.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from nengok.state.alembic_runner import NENGOK_ALEMBIC_VERSION_TABLE

config = context.config

target_metadata = None


def _version_table_schema() -> str | None:
    return config.attributes.get("version_table_schema")


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without opening a connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=NENGOK_ALEMBIC_VERSION_TABLE,
        version_table_schema=_version_table_schema(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through a live SQLAlchemy `Connection`."""
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            _run(connection)
        return

    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        version_table=NENGOK_ALEMBIC_VERSION_TABLE,
        version_table_schema=_version_table_schema(),
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
