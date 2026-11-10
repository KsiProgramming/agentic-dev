"""Selection gates (6.7): an approval keeps the keys of the items it chose, which the paused run
continues with.

Revision ID: 0028_approval_selection
Revises: 0027_workflow_publications
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0028_approval_selection"
down_revision: str | None = "0027_workflow_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("selection", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "selection")
