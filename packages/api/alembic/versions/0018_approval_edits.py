"""Gate edits: an approval may carry the approver's edits to the files the run's writers changed,
which the gate commits before the run goes on. Approvals made before have none.

Revision ID: 0018_approval_edits
Revises: 0017_optional_budget
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018_approval_edits"
down_revision: str | None = "0017_optional_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A list of `{node_id, path, content}`; NULL is no edits.
    op.add_column("approvals", sa.Column("edits", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "edits")
