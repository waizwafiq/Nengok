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
        op.drop_index(old, table_name=table, schema=schema)
        op.create_index(new, table, _index_columns(new), schema=schema)


def downgrade() -> None:
    schema = current_schema()
    for old, new, table in _INDEX_RENAMES:
        op.drop_index(new, table_name=table, schema=schema)
        old_table = _strip_prefix(table)
        op.create_index(old, old_table, _index_columns(new), schema=schema)
    for old, new in reversed(_TABLE_RENAMES):
        op.rename_table(new, old, schema=schema)


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


def _strip_prefix(table: str) -> str:
    return table.removeprefix("nengok_")
