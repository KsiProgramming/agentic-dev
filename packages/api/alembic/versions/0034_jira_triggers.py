"""Jira triggers (7.3): the rules that start a run when an issue moves to a status or gets a
label (`jira_triggers`), the webhook each workspace holds on a site (`jira_webhooks`), the
deliveries received (`jira_deliveries`, unique per delivery for dedupe), what each rule did with
them (`jira_trigger_fires`), the moves runs made themselves (`jira_own_moves`), and on `runs` the
rule and issue that started a run.

Revision ID: 0034_jira_triggers
Revises: 0033_jira_connection
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_jira_triggers"
down_revision: str | None = "0033_jira_connection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "jira_triggers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("project_key", sa.String(32), nullable=False),
        sa.Column("on", sa.String(16), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("template_id", sa.String(128)),
        sa.Column("workflow_id", sa.String(64)),
        sa.Column("workflow_version", sa.Integer()),
        sa.Column("repo_url", sa.Text()),
        sa.Column("ref", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.CheckConstraint("\"on\" IN ('status', 'label')", name="ck_jira_triggers_on"),
        sa.CheckConstraint(
            "(template_id IS NULL) <> (workflow_id IS NULL)", name="ck_jira_triggers_target"
        ),
    )
    op.create_index(
        "ix_jira_triggers_workspace_site_project",
        "jira_triggers",
        ["workspace_id", "cloud_id", "project_key"],
    )
    op.create_table(
        "jira_webhooks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("webhook_id", sa.BigInteger()),
        sa.Column("url", sa.Text()),
        sa.Column(
            "projects", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("renewed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(64)),
        sa.Column("error_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.UniqueConstraint(
            "workspace_id", "cloud_id", name="uq_jira_webhooks_workspace_id_cloud_id"
        ),
    )
    op.create_index(
        "ix_jira_webhooks_cloud_id_webhook_id", "jira_webhooks", ["cloud_id", "webhook_id"]
    )
    op.create_table(
        "jira_deliveries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("delivery_id", sa.String(64), nullable=False),
        sa.Column("issue_key", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False, server_default="received"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.UniqueConstraint(
            "workspace_id", "cloud_id", "delivery_id", name="uq_jira_deliveries_delivery"
        ),
    )
    op.create_index("ix_jira_deliveries_received_at", "jira_deliveries", ["received_at"])
    op.create_table(
        "jira_trigger_fires",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "trigger_id",
            sa.Uuid(),
            sa.ForeignKey("jira_triggers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_id",
            sa.BigInteger(),
            sa.ForeignKey("jira_deliveries.id", ondelete="SET NULL"),
        ),
        sa.Column("issue_key", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index(
        "ix_jira_trigger_fires_trigger_at",
        "jira_trigger_fires",
        ["trigger_id", sa.text("at DESC")],
    )
    op.create_table(
        "jira_own_moves",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("issue_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(255), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
    )
    op.create_index("ix_jira_own_moves_issue", "jira_own_moves", ["cloud_id", "issue_key", "at"])
    op.add_column(
        "runs",
        sa.Column(
            "jira_trigger_id",
            sa.Uuid(),
            sa.ForeignKey("jira_triggers.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("runs", sa.Column("jira_issue", postgresql.JSONB()))
    op.create_index(
        "ix_runs_jira_trigger_active",
        "runs",
        ["jira_trigger_id"],
        postgresql_where=sa.text(
            "jira_trigger_id IS NOT NULL AND status IN ('queued', 'running', 'waiting')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_jira_trigger_active", table_name="runs")
    op.drop_column("runs", "jira_issue")
    op.drop_column("runs", "jira_trigger_id")
    op.drop_table("jira_own_moves")
    op.drop_table("jira_trigger_fires")
    op.drop_table("jira_deliveries")
    op.drop_table("jira_webhooks")
    op.drop_table("jira_triggers")
