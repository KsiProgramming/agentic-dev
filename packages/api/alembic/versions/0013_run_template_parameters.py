"""A template run keeps the options it was started with (`template_parameters`), so a later
"Edit and rerun" can offer them again. A rerun copies them with the rest of the run.

Revision ID: 0013_run_template_parameters
Revises: 0012_connection_account_type
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_run_template_parameters"
down_revision: str | None = "0012_connection_account_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("template_parameters", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "template_parameters")
