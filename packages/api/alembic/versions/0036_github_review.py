"""PR review feedback (7.6): the GitHub webhook deliveries received (`github_deliveries`, a retry
is dropped), on `runs` the pull request a follow-up works on (`pr_review`) and the review its
agents are told (`pr_review_brief`), and the workspace's `review_rounds` limit.

Revision ID: 0036_github_review
Revises: 0035_jira_field_mappings
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_github_review"
down_revision: str | None = "0035_jira_field_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_deliveries",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False, server_default="received"),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_github_deliveries_received_at", "github_deliveries", ["received_at"])
    op.add_column("runs", sa.Column("pr_review", postgresql.JSONB()))
    op.add_column("runs", sa.Column("pr_review_brief", postgresql.JSONB()))
    op.create_index(
        "ix_runs_pr_url",
        "runs",
        ["pr_url"],
        postgresql_where=sa.text("pr_url IS NOT NULL"),
    )
    op.create_index(
        "ix_runs_pr_review_url",
        "runs",
        [sa.text("(pr_review ->> 'pr_url')")],
        postgresql_where=sa.text("pr_review IS NOT NULL"),
    )
    op.add_column("workspace_policies", sa.Column("review_rounds", sa.Integer()))


def downgrade() -> None:
    op.drop_column("workspace_policies", "review_rounds")
    op.drop_index("ix_runs_pr_review_url", table_name="runs")
    op.drop_index("ix_runs_pr_url", table_name="runs")
    op.drop_column("runs", "pr_review_brief")
    op.drop_column("runs", "pr_review")
    op.drop_index("ix_github_deliveries_received_at", table_name="github_deliveries")
    op.drop_table("github_deliveries")
