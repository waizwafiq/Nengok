"""extend cycle history with status and counts

Revision ID: 0003_extend_cycle_history
Revises: 0002_rename_approval_columns
Create Date: 2026-06-02 00:00:02.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0003_extend_cycle_history"
down_revision: str | Sequence[str] | None = "0002_rename_approval_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    with op.batch_alter_table("cycles", schema=schema) as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="ok",
            )
        )
        batch.add_column(
            sa.Column(
                "clusters_processed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "clusters_discovered",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    schema = current_schema()
    with op.batch_alter_table("cycles", schema=schema) as batch:
        batch.drop_column("error_message")
        batch.drop_column("clusters_discovered")
        batch.drop_column("clusters_processed")
        batch.drop_column("status")
