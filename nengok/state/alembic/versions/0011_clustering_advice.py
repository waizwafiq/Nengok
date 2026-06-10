"""add nengok_clustering_advice table

Revision ID: 0011_clustering_advice
Revises: 0010_cluster_feedback
Create Date: 2026-06-10 00:00:00.000000

The retro pass proposes clustering-prompt amendments; a human activates
at most one per project. Same trust layer as fixes: the agent proposes,
the human disposes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0011_clustering_advice"
down_revision: str | Sequence[str] | None = "0010_cluster_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.create_table(
        "nengok_clustering_advice",
        sa.Column("advice_id", sa.String(length=64), primary_key=True),
        sa.Column("project", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prompt_amendment", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.String(length=40), nullable=True),
        schema=schema,
    )
    op.create_index(
        "nengok_clustering_advice_project_idx",
        "nengok_clustering_advice",
        ["project", "status"],
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_index(
        "nengok_clustering_advice_project_idx", table_name="nengok_clustering_advice", schema=schema
    )
    op.drop_table("nengok_clustering_advice", schema=schema)
