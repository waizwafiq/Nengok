"""add nengok_notifications table

Revision ID: 0006_add_nengok_notifications
Revises: 0005_add_approval_source
Create Date: 2026-06-04 00:00:00.000000

Generic notification delivery tracking for the notifier dispatcher.
Dedup key is UNIQUE(notifier_name, event_kind, subject_id) so Slack and
webhook notifiers never suppress each other for the same event.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nengok.state.alembic._helpers import current_schema

revision: str = "0006_add_nengok_notifications"
down_revision: str | Sequence[str] | None = "0005_add_approval_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    schema = current_schema()
    op.create_table(
        "nengok_notifications",
        sa.Column("notification_id", sa.String(length=64), primary_key=True),
        sa.Column("notifier_name", sa.String(length=64), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notifier_state", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.UniqueConstraint(
            "notifier_name", "event_kind", "subject_id", name="nengok_notifications_dedup_uniq"
        ),
        schema=schema,
    )
    op.create_index(
        "nengok_notifications_subject_idx",
        "nengok_notifications",
        ["subject_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema = current_schema()
    op.drop_index("nengok_notifications_subject_idx", table_name="nengok_notifications", schema=schema)
    op.drop_table("nengok_notifications", schema=schema)
