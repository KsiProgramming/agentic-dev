"""Runs can be cancelled: `cancel_requested_at` is set when a user asks, and the worker running
the run (or the next one to claim it) ends it `cancelled`.

Revision ID: 0011_run_cancel
Revises: 0010_run_summary
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_run_cancel"
down_revision: str | None = "0010_run_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("runs", "cancel_requested_at")
