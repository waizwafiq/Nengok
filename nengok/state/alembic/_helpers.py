"""Shared helpers for Nengok Alembic revisions."""

from __future__ import annotations

from alembic import op


def current_schema() -> str | None:
    """
    Return the schema configured on the active `MigrationContext`.

    `env.py` forwards `database_schema` from the resolved `NengokConfig`
    into `context.configure(version_table_schema=...)`, and Alembic
    surfaces the value at `MigrationContext.version_table_schema`.
    Revisions pull it through this helper and pass it to every
    `op.create_table`, `op.create_index`, `op.rename_table`, and
    `op.batch_alter_table` call so the entire Nengok schema lands in
    one Postgres namespace when the operator opts in.
    """
    return op.get_context().version_table_schema
