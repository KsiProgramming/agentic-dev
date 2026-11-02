"""Workflow versions (5.7): a version a restore copied names the one it copied, and a run started
from a stored workflow keeps its id and version.

Revision ID: 0025_workflow_restore
Revises: 0024_workflows
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_workflow_restore"
down_revision: str | None = "0024_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_versions", sa.Column("restored_from", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("workflow_id", sa.String(64), nullable=True))
    op.add_column("runs", sa.Column("workflow_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "workflow_version")
    op.drop_column("runs", "workflow_id")
    op.drop_column("workflow_versions", "restored_from")
