"""add nengok_cluster_feedback table

Revision ID: 0010_cluster_feedback
Revises: 0009_cluster_links
Create Date: 2026-06-10 00:00:00.000000

Reviewer decisions become clustering signal: every approve, reject,
dismiss, tag, or wrong-merge flag lands here so the clusterer prompt
can carry past corrections back into the next cycle.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0010_cluster_feedback"
down_revision: str | Sequence[str] | None = "0009_cluster_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.create_table(
        "nengok_cluster_feedback",
        sa.Column("feedback_id", sa.String(length=64), primary_key=True),
        sa.Column("cluster_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["nengok_clusters.cluster_id"]),
        schema=schema,
    )
    op.create_index(
        "nengok_cluster_feedback_cluster_idx",
        "nengok_cluster_feedback",
        ["cluster_id"],
        schema=schema,
    )
    op.create_index(
        "nengok_cluster_feedback_created_idx",
        "nengok_cluster_feedback",
        ["created_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_index("nengok_cluster_feedback_created_idx", table_name="nengok_cluster_feedback", schema=schema)
    op.drop_index("nengok_cluster_feedback_cluster_idx", table_name="nengok_cluster_feedback", schema=schema)
    op.drop_table("nengok_cluster_feedback", schema=schema)
