"""A workspace's Jira connection (7.1): an OAuth grant stored as the connection's encrypted
secret (no key hint: its tokens rotate), the scopes it holds, why it needs attention, the sites
it reaches (`jira_sites`) and the projects the workspace may use on each (`jira_projects`).

Revision ID: 0033_jira_connection
Revises: 0032_rerun_from_step
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_jira_connection"
down_revision: str | None = "0032_rerun_from_step"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_connections_provider_columns"
_OLD_CHECK = (
    "(provider = 'github' AND external_id IS NOT NULL) OR "
    "(provider <> 'github' AND secret_nonce IS NOT NULL AND secret_ciphertext IS NOT NULL "
    "AND key_hint IS NOT NULL)"
)
_NEW_CHECK = (
    "(provider = 'github' AND external_id IS NOT NULL) OR "
    "(provider = 'jira' AND secret_nonce IS NOT NULL AND secret_ciphertext IS NOT NULL) OR "
    "(provider NOT IN ('github', 'jira') AND secret_nonce IS NOT NULL "
    "AND secret_ciphertext IS NOT NULL AND key_hint IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column("connections", sa.Column("scopes", postgresql.JSONB()))
    op.add_column("connections", sa.Column("needs_attention", sa.String(64)))
    op.drop_constraint(_CHECK, "connections", type_="check")
    op.create_check_constraint(_CHECK, "connections", _NEW_CHECK)
    op.create_table(
        "jira_sites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cloud_id", sa.String(64), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "connection_id", "cloud_id", name="uq_jira_sites_connection_id_cloud_id"
        ),
    )
    op.create_table(
        "jira_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Uuid(),
            sa.ForeignKey("jira_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("key", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.UniqueConstraint("site_id", "project_id", name="uq_jira_projects_site_id_project_id"),
    )


def downgrade() -> None:
    op.drop_table("jira_projects")
    op.drop_table("jira_sites")
    # A Jira connection has no key hint, which the old check requires.
    op.execute("DELETE FROM connections WHERE provider = 'jira'")
    op.drop_constraint(_CHECK, "connections", type_="check")
    op.create_check_constraint(_CHECK, "connections", _OLD_CHECK)
    op.drop_column("connections", "needs_attention")
    op.drop_column("connections", "scopes")
