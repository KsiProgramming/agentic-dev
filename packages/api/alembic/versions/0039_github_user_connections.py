"""Personal GitHub connections for Copilot (8.2): one row per person in a workspace
(`github_user_connections`, the encrypted grant and the GitHub login), and on `runs` the
connection whose Copilot the run uses and the login as it was.

Revision ID: 0039_github_user_connections
Revises: 0038_approval_iteration
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_github_user_connections"
down_revision: str | None = "0038_approval_iteration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_user_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(255), nullable=False),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", postgresql.JSONB()),
        sa.Column("needs_attention", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "workspace_id", "github_user_id", name="uq_github_user_connections_workspace_user"
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "copilot_connection_id",
            sa.Uuid(),
            sa.ForeignKey("github_user_connections.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("runs", sa.Column("copilot_login", sa.String(255)))


def downgrade() -> None:
    op.drop_column("runs", "copilot_login")
    op.drop_column("runs", "copilot_connection_id")
    op.drop_table("github_user_connections")
