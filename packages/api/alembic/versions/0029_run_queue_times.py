"""Queue recovery (12.1): when a run last became `queued` and when the queue sweep last pushed its
id to Redis again. Postgres is the queue's source of truth: a run `queued` with no lease past a
threshold is announced again (`agentic_store.queue.requeue_stale_runs`).

Revision ID: 0029_run_queue_times
Revises: 0028_approval_selection
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_run_queue_times"
down_revision: str | None = "0028_approval_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True))
    # A run queued before this revision counts from its creation (the best we know).
    op.execute("UPDATE runs SET queued_at = created_at")
    op.alter_column("runs", "queued_at", nullable=False, server_default=sa.text("now()"))
    op.create_index(
        "ix_runs_queued_unleased",
        "runs",
        ["queued_at"],
        postgresql_where=sa.text("status = 'queued' AND lease_expires_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_queued_unleased", table_name="runs")
    op.drop_column("runs", "enqueued_at")
    op.drop_column("runs", "queued_at")
