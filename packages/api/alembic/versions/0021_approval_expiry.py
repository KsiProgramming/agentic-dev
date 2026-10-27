"""Approval expiry: when the gate a run waits at expires (`runs.gate_expires_at`), why a run was
cancelled (`runs.cancel_reason`), and a workspace's own `approval_ttl_s`.

Gates that paused before this had no time to live; each gets the platform's 72 h from when it
started waiting, so the first expiry sweep after the deploy cancels those already older than that.

Revision ID: 0021_approval_expiry
Revises: 0020_active_waiting_time
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_approval_expiry"
down_revision: str | None = "0020_active_waiting_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `agentic_engine.policy.APPROVAL_TTL_S`, as it was when this ran.
APPROVAL_TTL = "72 hours"

BACKFILL = f"""
UPDATE runs SET
    gate_expires_at = coalesce(waiting_since, updated_at) + interval '{APPROVAL_TTL}',
    waiting_gate = waiting_gate || jsonb_build_object(
        'expires_at',
        to_char(
            (coalesce(waiting_since, updated_at) + interval '{APPROVAL_TTL}') AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"'
        )
    )
WHERE status = 'waiting' AND waiting_gate IS NOT NULL
"""


def upgrade() -> None:
    op.add_column("runs", sa.Column("gate_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("workspace_policies", sa.Column("approval_ttl_s", sa.Integer(), nullable=True))
    op.create_index(
        "ix_runs_gate_expires_at",
        "runs",
        ["gate_expires_at"],
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.execute(BACKFILL)
    op.execute(
        "UPDATE runs SET cancel_reason = 'cancelled by user' "
        "WHERE status = 'cancelled' AND cancel_requested_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_runs_gate_expires_at", table_name="runs")
    op.drop_column("workspace_policies", "approval_ttl_s")
    op.drop_column("runs", "cancel_reason")
    op.drop_column("runs", "gate_expires_at")
