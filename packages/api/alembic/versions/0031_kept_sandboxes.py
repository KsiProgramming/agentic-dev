"""A failed, cancelled or expired run keeps its code (12.3): until when its sandbox is kept and
when it was removed (`runs.sandbox_kept_until`, `runs.sandbox_removed_at`), the workspace limits
`sandbox_ttl_s` and `branch_retention_days`, and on each saved branch version the files it
changed (`changes`, `changes_error`), a `wip` kind for uncommitted work, and its bundle made
optional (`bundle_removed_at` once dropped past the retention).

Revision ID: 0031_kept_sandboxes
Revises: 0030_run_branches
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_kept_sandboxes"
down_revision: str | None = "0030_run_branches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("sandbox_kept_until", sa.DateTime(timezone=True)))
    op.add_column("runs", sa.Column("sandbox_removed_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_runs_sandbox_kept_until",
        "runs",
        ["sandbox_kept_until"],
        postgresql_where=sa.text("sandbox_removed_at IS NULL"),
    )
    op.add_column("workspace_policies", sa.Column("sandbox_ttl_s", sa.Integer()))
    op.add_column("workspace_policies", sa.Column("branch_retention_days", sa.Integer()))
    op.alter_column("run_branches", "data", nullable=True)
    op.add_column("run_branches", sa.Column("changes", postgresql.JSONB()))
    op.add_column("run_branches", sa.Column("changes_error", sa.Text()))
    op.add_column("run_branches", sa.Column("bundle_removed_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_run_branches_kind", "run_branches", type_="check")
    op.create_check_constraint(
        "ck_run_branches_kind", "run_branches", "kind IN ('writer', 'integration', 'wip')"
    )


def downgrade() -> None:
    # Versions this schema cannot hold go: uncommitted work, and bundles already dropped.
    op.execute("DELETE FROM run_branches WHERE kind = 'wip' OR data IS NULL")
    op.drop_constraint("ck_run_branches_kind", "run_branches", type_="check")
    op.create_check_constraint(
        "ck_run_branches_kind", "run_branches", "kind IN ('writer', 'integration')"
    )
    op.drop_column("run_branches", "bundle_removed_at")
    op.drop_column("run_branches", "changes_error")
    op.drop_column("run_branches", "changes")
    op.alter_column("run_branches", "data", nullable=False)
    op.drop_column("workspace_policies", "branch_retention_days")
    op.drop_column("workspace_policies", "sandbox_ttl_s")
    op.drop_index("ix_runs_sandbox_kept_until", table_name="runs")
    op.drop_column("runs", "sandbox_removed_at")
    op.drop_column("runs", "sandbox_kept_until")
