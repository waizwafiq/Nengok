"""rename approval columns to reviewer/created_at/reason

Revision ID: 0002_rename_approval_columns
Revises: 0001_initial_schema
Create Date: 2026-06-02 00:00:01.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_rename_approval_columns"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.alter_column("decided_by", new_column_name="reviewer", existing_type=sa.Text())
        batch.alter_column(
            "decided_at",
            new_column_name="created_at",
            existing_type=sa.String(length=40),
            existing_nullable=False,
        )
        batch.alter_column("notes", new_column_name="reason", existing_type=sa.Text())
    op.create_index("approvals_created_idx", "approvals", ["created_at"])


def downgrade() -> None:
    op.drop_index("approvals_created_idx", table_name="approvals")
    with op.batch_alter_table("approvals") as batch:
        batch.alter_column("reason", new_column_name="notes", existing_type=sa.Text())
        batch.alter_column(
            "created_at",
            new_column_name="decided_at",
            existing_type=sa.String(length=40),
            existing_nullable=False,
        )
        batch.alter_column("reviewer", new_column_name="decided_by", existing_type=sa.Text())
