"""Runs list v2: what started a run (`runs.trigger`) and the branch it works on (`runs.branch`).

Existing runs get `rerun` if they repeat another run, `manual` if they were built from a template
(the web's New run sheet is the only client that sends one), else `api`. Their branch is the ref
they asked for, else the default branch of a repo they created.

Revision ID: 0022_runs_trigger_branch
Revises: 0021_approval_expiry
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_runs_trigger_branch"
down_revision: str | None = "0021_approval_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_TRIGGER = """
UPDATE runs SET trigger = CASE
    WHEN rerun_of IS NOT NULL THEN 'rerun'
    WHEN template_id IS NOT NULL THEN 'manual'
    ELSE 'api'
END
"""

BACKFILL_BRANCH = """
UPDATE runs SET branch = coalesce(
    nullif(repo->>'ref', ''),
    (
        SELECT e.payload->>'default_branch' FROM run_events e
        WHERE e.run_id = runs.id AND e.type = 'repo_created'
        ORDER BY e.seq LIMIT 1
    )
)
"""


def upgrade() -> None:
    op.add_column("runs", sa.Column("trigger", sa.String(32), nullable=False, server_default="api"))
    op.add_column("runs", sa.Column("branch", sa.Text(), nullable=True))
    op.execute(BACKFILL_TRIGGER)
    op.execute(BACKFILL_BRANCH)


def downgrade() -> None:
    op.drop_column("runs", "branch")
    op.drop_column("runs", "trigger")
