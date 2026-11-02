"""Stored workflows (5.1): a workflow per workspace and id, and its versions, each the spec a
batch of graph operations made. A trigger refuses updates and deletes of a version.

Revision ID: 0024_workflows
Revises: 0023_run_artifacts
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0024_workflows"
down_revision: str | None = "0023_run_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION workflow_versions_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'workflow_versions is append-only';
END
$$
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER workflow_versions_append_only BEFORE UPDATE OR DELETE ON workflow_versions
    FOR EACH ROW EXECUTE FUNCTION workflow_versions_append_only()
"""


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("spec", JSONB(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("ops", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "workflow_id"],
            ["workflows.workspace_id", "workflows.id"],
            name="fk_workflow_versions_workflow",
        ),
        sa.CheckConstraint("version >= 1", name="ck_workflow_versions_version"),
    )
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    op.drop_table("workflow_versions")
    op.execute("DROP FUNCTION workflow_versions_append_only()")
    op.drop_table("workflows")
