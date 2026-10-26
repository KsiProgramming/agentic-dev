"""Audit log: one append-only row per action in a workspace, written with the change it records.
A trigger refuses updates and deletes. Runs and approvals made before are backfilled from their
rows; settings changes made before were never recorded, so none are invented.

Revision ID: 0019_audit_events
Revises: 0018_approval_edits
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019_audit_events"
down_revision: str | None = "0018_approval_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END
$$
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
"""

# In time order, so ids grow with `at` like the rows written from now on. A cancelled run's
# status before the request is not known any more.
BACKFILL = """
INSERT INTO audit_events (workspace_id, at, action, actor_type, run_id, node_id, details)
SELECT workspace_id, at, action, actor_type, run_id, node_id, details FROM (
    SELECT workspace_id, created_at AS at,
        CASE WHEN rerun_of IS NULL THEN 'run.created' ELSE 'run.rerun' END AS action,
        'user' AS actor_type, id AS run_id, NULL AS node_id,
        jsonb_strip_nulls(jsonb_build_object('rerun_of', rerun_of::text))
            || jsonb_build_object(
                'template_id', template_id,
                'repo_url', repo_url,
                'budget_usd', COALESCE(policy -> 'budget_usd', 'null'::jsonb)
            ) AS details
    FROM runs
    UNION ALL
    SELECT workspace_id, cancel_requested_at, 'run.cancel_requested', 'user', id, NULL,
        '{}'::jsonb
    FROM runs WHERE cancel_requested_at IS NOT NULL
    UNION ALL
    SELECT r.workspace_id, a.created_at,
        CASE a.decision WHEN 'approve' THEN 'gate.approved' ELSE 'gate.rejected' END,
        'user', a.run_id, a.node_id,
        jsonb_build_object(
            'comment', a.comment,
            'edited_files', COALESCE(jsonb_array_length(a.edits), 0),
            'edited_paths', COALESCE(
                (SELECT jsonb_agg(e -> 'path') FROM jsonb_array_elements(a.edits) e), '[]'::jsonb
            )
        )
    FROM approvals a JOIN runs r ON r.id = a.run_id
    UNION ALL
    SELECT workspace_id, COALESCE(finished_at, updated_at), 'run.ended', 'system', id, NULL,
        jsonb_build_object(
            'status', status,
            'failure_reason', failure_reason,
            'pr_url', pr_url,
            'estimated_usd', estimated_usd::text,
            'cost_complete', cost_complete
        )
    FROM runs WHERE status IN ('completed', 'failed', 'cancelled')
) backfill
ORDER BY at, run_id, action
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        # Who acted; NULL until users and auth exist.
        sa.Column("actor_id", sa.String(255), nullable=True),
        # No foreign key: an entry outlives what it names.
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.String(64), nullable=True),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint("actor_type IN ('user', 'system')", name="ck_audit_events_actor_type"),
    )
    op.create_index(
        "ix_audit_events_workspace_at",
        "audit_events",
        ["workspace_id", sa.text("at DESC"), sa.text("id DESC")],
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.execute(BACKFILL)
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
