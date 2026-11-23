"""Independent review (13.6): `approvals.dismissed`, the fingerprints of the review comments an
approver dismissed at a gate with `review`, which the pull request's notes leave out. NULL for
every other approval.

Revision ID: 0042_review_dismissals
Revises: 0041_protected_attempts
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_review_dismissals"
down_revision: str | None = "0041_protected_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("dismissed", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "dismissed")
