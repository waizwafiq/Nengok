"""add nengok_cluster_links table

Revision ID: 0009_cluster_links
Revises: 0008_cluster_project
Create Date: 2026-06-10 00:00:00.000000

Cross-agent cluster links: a judge-confirmed pair of clusters in
different projects that share an upstream cause. Pairs are stored in
canonical order (cluster_id_a < cluster_id_b) so the unique key dedups
regardless of discovery order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0009_cluster_links"
down_revision: str | Sequence[str] | None = "0008_cluster_project"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.create_table(
        "nengok_cluster_links",
        sa.Column("link_id", sa.String(length=64), primary_key=True),
        sa.Column("cluster_id_a", sa.String(length=64), nullable=False),
        sa.Column("cluster_id_b", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id_a"], ["nengok_clusters.cluster_id"]),
        sa.ForeignKeyConstraint(["cluster_id_b"], ["nengok_clusters.cluster_id"]),
        sa.UniqueConstraint("cluster_id_a", "cluster_id_b", name="nengok_cluster_links_pair_uniq"),
        schema=schema,
    )
    op.create_index(
        "nengok_cluster_links_a_idx",
        "nengok_cluster_links",
        ["cluster_id_a"],
        schema=schema,
    )
    op.create_index(
        "nengok_cluster_links_b_idx",
        "nengok_cluster_links",
        ["cluster_id_b"],
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_index("nengok_cluster_links_b_idx", table_name="nengok_cluster_links", schema=schema)
    op.drop_index("nengok_cluster_links_a_idx", table_name="nengok_cluster_links", schema=schema)
    op.drop_table("nengok_cluster_links", schema=schema)
