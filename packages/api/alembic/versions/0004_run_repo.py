"""Runs may name the repo they work on (a `RepoSource`); null for runs without one.

Revision ID: 0004_run_repo
Revises: 0003_run_spec
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_run_repo"
down_revision: str | None = "0003_run_spec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("repo", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "repo")
