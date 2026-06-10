"""add project to nengok_clusters and projects_json to nengok_cycles

Revision ID: 0008_cluster_project
Revises: 0007_cluster_signals
Create Date: 2026-06-10 00:00:00.000000

Multi-project monitoring: every cluster row records which Phoenix
project produced it, and every cycle row records the set of projects
the cycle covered plus how many clusters the identity matcher merged.
A NULL project predates this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0008_cluster_project"
down_revision: str | Sequence[str] | None = "0007_cluster_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.add_column(
        "nengok_clusters",
        sa.Column("project", sa.String(length=255), nullable=True),
        schema=schema,
    )
    op.create_index(
        "nengok_clusters_project_idx",
        "nengok_clusters",
        ["project"],
        schema=schema,
    )
    op.add_column(
        "nengok_cycles",
        sa.Column("projects_json", sa.Text(), nullable=True),
        schema=schema,
    )
    op.add_column(
        "nengok_cycles",
        sa.Column("clusters_merged", sa.Integer(), nullable=False, server_default="0"),
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_column("nengok_cycles", "clusters_merged", schema=schema)
    op.drop_column("nengok_cycles", "projects_json", schema=schema)
    op.drop_index("nengok_clusters_project_idx", table_name="nengok_clusters", schema=schema)
    op.drop_column("nengok_clusters", "project", schema=schema)
