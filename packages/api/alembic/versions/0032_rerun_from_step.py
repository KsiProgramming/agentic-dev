"""Rerun from a step (12.4): the top-level step each saved branch version was saved in
(`run_branches.step`), and what a rerun from a step starts from (`runs.rerun_from`: the step's
`node_id`, `use_wip`, and the parameter paths it `edited`).

Revision ID: 0032_rerun_from_step
Revises: 0031_kept_sandboxes
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_rerun_from_step"
down_revision: str | None = "0031_kept_sandboxes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run_branches", sa.Column("step", sa.String(128)))
    op.add_column("runs", sa.Column("rerun_from", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("runs", "rerun_from")
    op.drop_column("run_branches", "step")
