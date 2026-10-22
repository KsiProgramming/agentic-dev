"""Approvals: the human decisions at a run's gates.

Revision ID: 0009_approvals
Revises: 0008_github_connections
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_approvals"
down_revision: str | None = "0008_github_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Also serves lookups by run_id.
        sa.UniqueConstraint("run_id", "node_id", name="uq_approvals_run_id_node_id"),
        sa.CheckConstraint("decision IN ('approve', 'reject')", name="ck_approvals_decision"),
    )


def downgrade() -> None:
    op.drop_table("approvals")
