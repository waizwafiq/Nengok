"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.create_table(
        "clusters",
        sa.Column("cluster_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("hypothesis_json", sa.Text(), nullable=True),
        sa.Column("member_spans_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("first_seen", sa.String(length=40), nullable=True),
        sa.Column("diagnosed_at", sa.String(length=40), nullable=True),
        schema=schema,
    )
    op.create_index("clusters_status_idx", "clusters", ["status"], schema=schema)

    op.create_table(
        "seen_spans",
        sa.Column("span_id", sa.String(length=128), primary_key=True),
        sa.Column("cluster_id", sa.String(length=64), nullable=True),
        sa.Column("first_seen", sa.String(length=40), nullable=False),
        schema=schema,
    )

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=64), primary_key=True),
        sa.Column("cluster_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.cluster_id"]),
        schema=schema,
    )
    op.create_index("approvals_cluster_idx", "approvals", ["cluster_id"], schema=schema)

    op.create_table(
        "experiments",
        sa.Column("row_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("experiment_id", sa.String(length=128), nullable=True),
        sa.Column("cluster_id", sa.String(length=64), nullable=False),
        sa.Column("experiment_name", sa.Text(), nullable=False),
        sa.Column("dataset_name", sa.Text(), nullable=False),
        sa.Column("baseline_pass_rate", sa.Float(), nullable=False),
        sa.Column("fix_pass_rate", sa.Float(), nullable=False),
        sa.Column("golden_baseline_pass_rate", sa.Float(), nullable=False),
        sa.Column("golden_fix_pass_rate", sa.Float(), nullable=False),
        sa.Column("per_case_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.cluster_id"]),
        schema=schema,
    )
    op.create_index("experiments_cluster_idx", "experiments", ["cluster_id"], schema=schema)
    op.create_index("experiments_created_idx", "experiments", ["created_at"], schema=schema)

    op.create_table(
        "cycles",
        sa.Column("cycle_id", sa.String(length=64), primary_key=True),
        sa.Column("started_at", sa.String(length=40), nullable=False),
        sa.Column("ended_at", sa.String(length=40), nullable=False),
        sa.Column("gemini_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gemini_dollars", sa.Float(), nullable=False, server_default="0.0"),
        schema=schema,
    )
    op.create_index("cycles_started_idx", "cycles", ["started_at"], schema=schema)


def downgrade() -> None:
    schema = current_schema()
    op.drop_index("cycles_started_idx", table_name="cycles", schema=schema)
    op.drop_table("cycles", schema=schema)
    op.drop_index("experiments_created_idx", table_name="experiments", schema=schema)
    op.drop_index("experiments_cluster_idx", table_name="experiments", schema=schema)
    op.drop_table("experiments", schema=schema)
    op.drop_index("approvals_cluster_idx", table_name="approvals", schema=schema)
    op.drop_table("approvals", schema=schema)
    op.drop_table("seen_spans", schema=schema)
    op.drop_index("clusters_status_idx", table_name="clusters", schema=schema)
    op.drop_table("clusters", schema=schema)
