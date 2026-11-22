"""Provider selection (8.3): on `workspaces` the default provider, the Copilot model and the price
of a Copilot AI credit; on `runs` the provider the run was started on (`provider`), the providers
its agents use (`providers`) and the frozen resolution of each agent's provider and model
(`provider_map`). A run started on a person's Copilot (8.2) is backfilled as `copilot`.

Revision ID: 0040_provider_selection
Revises: 0039_github_user_connections
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_provider_selection"
down_revision: str | None = "0039_github_user_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("default_provider", sa.String(16)))
    op.add_column("workspaces", sa.Column("copilot_model", sa.String(128)))
    op.add_column("workspaces", sa.Column("copilot_credit_usd", sa.Numeric(10, 6)))
    op.add_column(
        "runs", sa.Column("provider", sa.String(16), server_default="claude", nullable=False)
    )
    op.add_column(
        "runs",
        sa.Column(
            "providers",
            postgresql.ARRAY(sa.String(16)),
            server_default=sa.text("ARRAY['claude']::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column("runs", sa.Column("provider_map", postgresql.JSONB()))
    op.execute(
        "UPDATE runs SET provider = 'copilot', providers = ARRAY['copilot']::varchar[] "
        "WHERE copilot_connection_id IS NOT NULL OR copilot_login IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("runs", "provider_map")
    op.drop_column("runs", "providers")
    op.drop_column("runs", "provider")
    op.drop_column("workspaces", "copilot_credit_usd")
    op.drop_column("workspaces", "copilot_model")
    op.drop_column("workspaces", "default_provider")
