"""A workspace may override the list price of a model (negotiated rates, a proxy model). Runs
price their usage with the workspace's prices when they log it.

Revision ID: 0015_workspace_model_prices
Revises: 0014_run_usage
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_workspace_model_prices"
down_revision: str | None = "0014_run_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICE_COLUMNS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


def upgrade() -> None:
    op.create_table(
        "workspace_model_prices",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("model", sa.String(128), primary_key=True),
        # USD per million tokens.
        *(sa.Column(name, sa.Numeric(12, 4), nullable=False) for name in PRICE_COLUMNS),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_model_prices")
