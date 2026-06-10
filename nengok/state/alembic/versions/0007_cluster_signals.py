"""add signals_json to nengok_clusters

Revision ID: 0007_cluster_signals
Revises: 0006_add_nengok_notifications
Create Date: 2026-06-10 00:00:00.000000

The cross-cycle cluster matcher gates its judge pass on shared anomaly
signals, so the signal profile a cluster was built from must survive
the process that discovered it. NULL means the row predates this
revision; the matcher treats it as an empty profile.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0007_cluster_signals"
down_revision: str | Sequence[str] | None = "0006_add_nengok_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.add_column(
        "nengok_clusters",
        sa.Column("signals_json", sa.Text(), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_column("nengok_clusters", "signals_json", schema=schema)
