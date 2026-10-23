"""Optional budget: a workspace may set a default USD budget for its runs. A run keeps its budget
in `runs.policy` (`budget_usd`); runs created before have none, which is no cost cap.

Revision ID: 0017_optional_budget
Revises: 0016_policy_limits
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_optional_budget"
down_revision: str | None = "0016_policy_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL is no budget; the same precision as `runs.estimated_usd`.
    op.add_column(
        "workspace_policies",
        sa.Column(
            "budget_usd",
            sa.Numeric(16, 8),
            sa.CheckConstraint("budget_usd > 0", name="workspace_policies_budget_usd_check"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workspace_policies", "budget_usd")
