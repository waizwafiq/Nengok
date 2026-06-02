"""rename every Nengok table with the nengok_ prefix

Revision ID: 0004_prefix_tables_with_nengok
Revises: 0003_extend_cycle_history
Create Date: 2026-06-02 00:00:03.000000

The prefix prevents collisions with user tables when DATABASE_URL points
at a database Nengok shares with the operator's own application. Indexes
are renamed alongside their tables so a later migration can rely on a
single naming convention.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0004_prefix_tables_with_nengok"
down_revision: str | Sequence[str] | None = "0003_extend_cycle_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_RENAMES: tuple[tuple[str, str], ...] = (
    ("clusters", "nengok_clusters"),
    ("seen_spans", "nengok_seen_spans"),
    ("approvals", "nengok_approvals"),
    ("experiments", "nengok_experiments"),
    ("cycles", "nengok_cycles"),
)

_INDEX_RENAMES: tuple[tuple[str, str, str], ...] = (
    ("clusters_status_idx", "nengok_clusters_status_idx", "nengok_clusters"),
    ("approvals_cluster_idx", "nengok_approvals_cluster_idx", "nengok_approvals"),
    ("approvals_created_idx", "nengok_approvals_created_idx", "nengok_approvals"),
    ("experiments_cluster_idx", "nengok_experiments_cluster_idx", "nengok_experiments"),
    ("experiments_created_idx", "nengok_experiments_created_idx", "nengok_experiments"),
    ("cycles_started_idx", "nengok_cycles_started_idx", "nengok_cycles"),
)


def upgrade() -> None:
    schema = current_schema()
    for old, new in _TABLE_RENAMES:
        op.rename_table(old, new, schema=schema)
    for old, new, table in _INDEX_RENAMES:
        _rename_index(old, new, table, schema=schema)


def downgrade() -> None:
    schema = current_schema()
    for old, new, table in _INDEX_RENAMES:
        _rename_index(new, old, table, schema=schema)
    for old, new in reversed(_TABLE_RENAMES):
        op.rename_table(new, old, schema=schema)


def _rename_index(old: str, new: str, table: str, *, schema: str | None) -> None:
    """
    Rename an index in place rather than drop + recreate.

    MySQL refuses to drop an index that backs a foreign key (errno 1553)
    so the SQLite drop + create path raises mid-migration. Postgres and
    MySQL 5.7+ both support a true rename, which leaves the FK index
    intact. SQLite has no `ALTER INDEX RENAME`, so it keeps the original
    drop + create path; SQLite does not enforce the FK index requirement
    the same way, so the drop is safe there.
    """
    dialect = op.get_bind().dialect.name
    if dialect == "mysql":
        qualified = f"{schema}.{table}" if schema else table
        op.execute(f"ALTER TABLE {qualified} RENAME INDEX {old} TO {new}")
    elif dialect == "postgresql":
        qualified = f"{schema}.{old}" if schema else old
        op.execute(f"ALTER INDEX {qualified} RENAME TO {new}")
    else:
        op.drop_index(old, table_name=table, schema=schema)
        op.create_index(new, table, _index_columns(new), schema=schema)


def _index_columns(new_index: str) -> list[str]:
    mapping = {
        "nengok_clusters_status_idx": ["status"],
        "nengok_approvals_cluster_idx": ["cluster_id"],
        "nengok_approvals_created_idx": ["created_at"],
        "nengok_experiments_cluster_idx": ["cluster_id"],
        "nengok_experiments_created_idx": ["created_at"],
        "nengok_cycles_started_idx": ["started_at"],
    }
    return mapping[new_index]
