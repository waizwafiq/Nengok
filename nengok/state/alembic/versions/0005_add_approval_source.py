"""add source discriminator to nengok_approvals

Revision ID: 0005_add_approval_source
Revises: 0004_prefix_tables_with_nengok
Create Date: 2026-06-02 00:00:04.000000

`source` records which operator surface wrote the approval
(`dashboard`, `tui`, or `api`). Compliance exports use it to attribute
decisions back to the channel that produced them. Existing rows are
backfilled to `dashboard` because every approval written before this
revision came from the browser UI.

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0005_add_approval_source"
down_revision: str | Sequence[str] | None = "0004_prefix_tables_with_nengok"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    with op.batch_alter_table("nengok_approvals", schema=schema) as batch:
        batch.add_column(
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default="dashboard",
            )
        )


def downgrade() -> None:
    schema = current_schema()
    with op.batch_alter_table("nengok_approvals", schema=schema) as batch:
        batch.drop_column("source")
