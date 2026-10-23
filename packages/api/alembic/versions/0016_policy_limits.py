"""Policy limits: a workspace may lower the platform's run limits, and each run keeps the limits
it was created with. Runs created before keep the platform policy of the time.

Revision ID: 0016_policy_limits
Revises: 0015_workspace_model_prices
Create Date: 2026-10-23
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016_policy_limits"
down_revision: str | None = "0015_workspace_model_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIMIT_COLUMNS = ("agents_alive", "agents_spawned", "max_depth", "loop_iterations", "wall_time_s")

# `agentic_engine.policy.PLATFORM_POLICY` at this revision; a migration does not import it, so
# it stays what it was when the migration ran.
PLATFORM_POLICY = {
    "agents_alive": 8,
    "agents_spawned": 40,
    "max_depth": 2,
    "loop_iterations": 5,
    "wall_time_s": 7200,
}


def upgrade() -> None:
    op.create_table(
        "workspace_policies",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        # NULL keeps the platform's limit; a value is at least 1 (the API caps it).
        *(
            sa.Column(name, sa.Integer(), sa.CheckConstraint(f"{name} >= 1"), nullable=True)
            for name in LIMIT_COLUMNS
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # Existing runs get the platform policy; new ones always set their own.
    op.add_column(
        "runs",
        sa.Column(
            "policy",
            JSONB(),
            nullable=False,
            server_default=sa.text(f"'{json.dumps(PLATFORM_POLICY)}'::jsonb"),
        ),
    )
    op.alter_column("runs", "policy", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "policy")
    op.drop_table("workspace_policies")
