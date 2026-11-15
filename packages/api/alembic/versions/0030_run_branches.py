"""Writers' commits saved outside the sandbox (12.2): the commit a run's first clone was at
(`runs.base_sha`), which its later sandboxes are cloned at, and every saved version of each of its
writers' and integration branches as a git bundle (`run_branches`, append only), restored into a
fresh sandbox.

Revision ID: 0030_run_branches
Revises: 0029_run_queue_times
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_run_branches"
down_revision: str | None = "0029_run_queue_times"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("base_sha", sa.String(40), nullable=True))
    op.create_table(
        "run_branches",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("branch", sa.String(255), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("node_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("commits", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('writer', 'integration')", name="ck_run_branches_kind"),
    )


def downgrade() -> None:
    op.drop_table("run_branches")
    op.drop_column("runs", "base_sha")
