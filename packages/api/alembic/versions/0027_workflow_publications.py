"""Composites (6.6): a published version of a workflow. A workflow with one is a composite, and
its unpublished versions are drafts. A trigger refuses updates and deletes, as for versions.

Revision ID: 0027_workflow_publications
Revises: 0026_run_subflows
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_workflow_publications"
down_revision: str | None = "0026_run_subflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION workflow_publications_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'workflow_publications is append-only';
END
$$
"""
APPEND_ONLY_TRIGGER = """
CREATE TRIGGER workflow_publications_append_only BEFORE UPDATE OR DELETE ON workflow_publications
    FOR EACH ROW EXECUTE FUNCTION workflow_publications_append_only()
"""


def upgrade() -> None:
    op.create_table(
        "workflow_publications",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "workflow_id", "version"],
            [
                "workflow_versions.workspace_id",
                "workflow_versions.workflow_id",
                "workflow_versions.version",
            ],
            name="fk_workflow_publications_version",
        ),
    )
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(APPEND_ONLY_TRIGGER)


def downgrade() -> None:
    op.drop_table("workflow_publications")
    op.execute("DROP FUNCTION workflow_publications_append_only()")
