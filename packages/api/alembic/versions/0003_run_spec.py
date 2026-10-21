"""Runs keep the spec and input they were started with; `queued` until a worker picks them up.

Revision ID: 0003_run_spec
Revises: 0002_run_events
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_run_spec"
down_revision: str | None = "0002_run_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rows from before this revision get an empty spec; new rows must set one.
    op.add_column(
        "runs",
        sa.Column(
            "spec", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.alter_column("runs", "spec", server_default=None)
    op.add_column("runs", sa.Column("input", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("runs", "input")
    op.drop_column("runs", "spec")
