"""GitHub connections: a workspace's App installation, stored without a secret.

The secret columns become nullable; `external_id` holds the installation id and `account_login`
the account it is installed on. A check constraint keeps each provider's required columns set.

Revision ID: 0008_github_connections
Revises: 0007_workspaces_connections
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_github_connections"
down_revision: str | None = "0007_workspaces_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `agentic_store.models.CONNECTION_COLUMNS_CHECK`.
CONNECTION_COLUMNS_CHECK = (
    "(provider = 'github' AND external_id IS NOT NULL) OR "
    "(provider <> 'github' AND secret_nonce IS NOT NULL AND secret_ciphertext IS NOT NULL "
    "AND key_hint IS NOT NULL)"
)
SECRET_COLUMNS = ("secret_nonce", "secret_ciphertext", "key_hint")


def upgrade() -> None:
    for column in SECRET_COLUMNS:
        op.alter_column("connections", column, nullable=True)
    op.add_column("connections", sa.Column("external_id", sa.BigInteger(), nullable=True))
    op.add_column("connections", sa.Column("account_login", sa.String(length=255), nullable=True))
    op.create_check_constraint(
        "ck_connections_provider_columns", "connections", sa.text(CONNECTION_COLUMNS_CHECK)
    )


def downgrade() -> None:
    op.drop_constraint("ck_connections_provider_columns", "connections", type_="check")
    op.execute(sa.text("DELETE FROM connections WHERE provider = 'github'"))
    op.drop_column("connections", "account_login")
    op.drop_column("connections", "external_id")
    for column in SECRET_COLUMNS:
        op.alter_column("connections", column, nullable=False)
