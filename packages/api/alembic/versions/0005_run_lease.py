"""Runs carry a lease: the worker running one holds it and renews it while it is alive, so
another worker can take over (and resume) a run whose lease has expired. `attempt` counts claims.

Revision ID: 0005_run_lease
Revises: 0004_run_repo
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_run_lease"
down_revision: str | None = "0004_run_repo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column("runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("attempt", sa.Integer(), server_default="0", nullable=False))
    op.create_index(
        "ix_runs_lease_expires_at",
        "runs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_lease_expires_at", table_name="runs")
    op.drop_column("runs", "attempt")
    op.drop_column("runs", "lease_expires_at")
    op.drop_column("runs", "worker_id")
