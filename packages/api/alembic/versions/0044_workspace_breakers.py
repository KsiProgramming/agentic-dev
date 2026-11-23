"""Circuit breakers (13.7): `workspace_policies.breakers`, the workspace's own breaker thresholds
by name (`repeat_calls`, `repeat_errors`, `cost_multiple`, `cost_floor_usd`, `flip_flops`); NULL
keeps the platform's.

Revision ID: 0044_workspace_breakers
Revises: 0043_circuit_breakers
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_workspace_breakers"
down_revision: str | None = "0043_circuit_breakers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspace_policies", sa.Column("breakers", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_policies", "breakers")
