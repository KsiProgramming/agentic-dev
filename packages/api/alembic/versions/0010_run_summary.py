"""Run summary: columns projected from a run's events, so runs can be listed without the log.

Existing runs are filled from their `run_events`; their `template_id` stays null (it was never
recorded).

Revision ID: 0010_run_summary
Revises: 0009_approvals
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010_run_summary"
down_revision: str | None = "0009_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "template_id",
    "repo_url",
    "started_at",
    "finished_at",
    "pr_url",
    "failure_reason",
    "waiting_gate",
    "rerun_of",
)

BACKFILL = """
UPDATE runs SET
    repo_url = runs.repo->>'url',
    started_at = (
        SELECT min(e.created_at) FROM run_events e
        WHERE e.run_id = runs.id AND e.type = 'run_started'
    ),
    finished_at = (
        SELECT max(e.created_at) FROM run_events e
        WHERE e.run_id = runs.id AND e.type IN ('run_completed', 'run_failed', 'run_cancelled')
    ),
    pr_url = (
        SELECT e.payload->>'url' FROM run_events e
        WHERE e.run_id = runs.id AND e.type = 'pr_opened'
        ORDER BY e.seq DESC LIMIT 1
    ),
    failure_reason = CASE WHEN runs.status = 'failed' THEN (
        SELECT CASE
            WHEN e.type = 'run_failed' THEN e.payload->>'error'
            ELSE 'node ' || e.node_id || ': ' || (e.payload->>'error')
        END
        FROM run_events e
        WHERE e.run_id = runs.id AND e.payload ? 'error'
            AND (e.type = 'run_failed' OR (e.type = 'node_failed' AND e.node_id IS NOT NULL))
        ORDER BY e.seq DESC LIMIT 1
    ) END,
    waiting_gate = CASE WHEN runs.status = 'waiting' THEN (
        SELECT jsonb_build_object('node_id', e.node_id, 'title', e.payload->>'title')
        FROM run_events e
        WHERE e.run_id = runs.id AND e.type = 'gate_waiting'
        ORDER BY e.seq DESC LIMIT 1
    ) END
"""


def upgrade() -> None:
    op.add_column("runs", sa.Column("template_id", sa.String(128), nullable=True))
    op.add_column("runs", sa.Column("repo_url", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("pr_url", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("waiting_gate", JSONB(), nullable=True))
    op.add_column("runs", sa.Column("rerun_of", sa.Uuid(), sa.ForeignKey("runs.id"), nullable=True))
    op.create_index(
        "ix_runs_workspace_created",
        "runs",
        ["workspace_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_index("ix_runs_workspace_created", table_name="runs")
    for column in reversed(COLUMNS):
        op.drop_column("runs", column)
