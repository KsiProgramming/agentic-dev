"""Spec from a Markdown file (7.7): on `runs`, the spec file a run was given as its input
(`spec_file`: `{source, name, path, ref, size, sha256, text}`).

Revision ID: 0037_run_spec_file
Revises: 0036_github_review
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_run_spec_file"
down_revision: str | None = "0036_github_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("spec_file", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("runs", "spec_file")
