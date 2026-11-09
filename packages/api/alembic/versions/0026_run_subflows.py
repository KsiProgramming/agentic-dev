"""Subflows (6.5): a run keeps a copy of every stored workflow version its spec calls, keyed
`<workflow id>@<version>`, so it runs, resumes and is shown from what it was created with.

Revision ID: 0026_run_subflows
Revises: 0025_workflow_restore
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0026_run_subflows"
down_revision: str | None = "0025_workflow_restore"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("subflows", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "subflows")
