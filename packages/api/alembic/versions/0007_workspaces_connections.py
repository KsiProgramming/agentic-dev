"""Workspaces and their encrypted connections; every run belongs to a workspace.

A default workspace is inserted and existing runs are moved into it. Its data key is made when
its first secret is stored, so this revision needs no master key.

Revision ID: 0007_workspaces_connections
Revises: 0006_checkpoints
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_workspaces_connections"
down_revision: str | None = "0006_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `agentic_store.models.DEFAULT_WORKSPACE_ID`; frozen here like the rest of the revision.
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=True),
        sa.Column("key_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("secret_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_hint", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "provider", name="uq_connections_workspace_id_provider"
        ),
    )
    op.execute(
        sa.text(
            "INSERT INTO workspaces (id, name) VALUES (CAST(:id AS uuid), 'Default')"
        ).bindparams(id=DEFAULT_WORKSPACE_ID)
    )

    op.add_column("runs", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE runs SET workspace_id = CAST(:id AS uuid)").bindparams(
            id=DEFAULT_WORKSPACE_ID
        )
    )
    op.alter_column("runs", "workspace_id", nullable=False)
    op.create_foreign_key(None, "runs", "workspaces", ["workspace_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("runs_workspace_id_fkey", "runs", type_="foreignkey")
    op.drop_column("runs", "workspace_id")
    op.drop_table("connections")
    op.drop_table("workspaces")
