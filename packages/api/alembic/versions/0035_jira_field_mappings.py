"""Jira field mapping (7.4): which of a picked project's fields holds its acceptance criteria and
its story points (`jira_field_mappings`, removed with the picked project), and on `runs` the
issue brief every agent of a Jira-triggered run is told (`jira_brief`).

Revision ID: 0035_jira_field_mappings
Revises: 0034_jira_triggers
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_jira_field_mappings"
down_revision: str | None = "0034_jira_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jira_field_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("jira_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("field_id", sa.String(255), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.UniqueConstraint("project_id", "role", name="uq_jira_field_mappings_project_id_role"),
        sa.CheckConstraint(
            "role IN ('acceptance_criteria', 'story_points')", name="ck_jira_field_mappings_role"
        ),
    )
    op.add_column("runs", sa.Column("jira_brief", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("runs", "jira_brief")
    op.drop_table("jira_field_mappings")
