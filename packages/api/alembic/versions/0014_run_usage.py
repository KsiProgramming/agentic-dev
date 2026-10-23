"""Runs keep their token and cost totals, added up from their `usage` events as they are
written, so the runs list shows cost without scanning the log.

Revision ID: 0014_run_usage
Revises: 0013_run_template_parameters
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_run_usage"
down_revision: str | None = "0013_run_template_parameters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOKEN_COLUMNS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def upgrade() -> None:
    for name in TOKEN_COLUMNS:
        op.add_column("runs", sa.Column(name, sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column(
        "runs",
        sa.Column("estimated_usd", sa.Numeric(16, 8), nullable=False, server_default="0"),
    )
    # False once a usage event had no price: `estimated_usd` is then a lower bound.
    op.add_column(
        "runs",
        sa.Column("cost_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # Runs logged before this revision: add up their usage events once.
    op.execute(
        """
        UPDATE runs SET
            input_tokens = u.input_tokens,
            output_tokens = u.output_tokens,
            cache_read_tokens = u.cache_read_tokens,
            cache_write_tokens = u.cache_write_tokens,
            estimated_usd = u.estimated_usd,
            cost_complete = u.cost_complete
        FROM (
            SELECT
                run_id,
                SUM(COALESCE((payload->>'input_tokens')::bigint, 0)) AS input_tokens,
                SUM(COALESCE((payload->>'output_tokens')::bigint, 0)) AS output_tokens,
                SUM(COALESCE((payload->>'cache_read_tokens')::bigint, 0)) AS cache_read_tokens,
                SUM(COALESCE((payload->>'cache_write_tokens')::bigint, 0)) AS cache_write_tokens,
                SUM(COALESCE((payload->>'estimated_usd')::numeric, 0)) AS estimated_usd,
                BOOL_AND(payload->>'estimated_usd' IS NOT NULL) AS cost_complete
            FROM run_events
            WHERE type = 'usage'
            GROUP BY run_id
        ) AS u
        WHERE runs.id = u.run_id
        """
    )


def downgrade() -> None:
    op.drop_column("runs", "cost_complete")
    op.drop_column("runs", "estimated_usd")
    for name in reversed(TOKEN_COLUMNS):
        op.drop_column("runs", name)
