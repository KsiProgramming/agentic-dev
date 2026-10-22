"""A GitHub connection records whether its installation is on a user or an organisation, so the
web app can link to the installation's settings page on GitHub.

Revision ID: 0012_connection_account_type
Revises: 0011_run_cancel
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_connection_account_type"
down_revision: str | None = "0011_run_cancel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("account_type", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("connections", "account_type")
