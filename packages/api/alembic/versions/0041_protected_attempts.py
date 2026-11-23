"""Protected paths (13.5): `runs.protected_attempts`, how many times a writer tried to change a
protected path (one per `protected_path_refused` event), kept as a summary column so the runs
list never scans the event log. Backfilled from the events.

Revision ID: 0041_protected_attempts
Revises: 0040_provider_selection
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_protected_attempts"
down_revision: str | None = "0040_provider_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("protected_attempts", sa.Integer(), server_default="0", nullable=False)
    )
    op.execute(
        "UPDATE runs SET protected_attempts = counted.n FROM ("
        "SELECT run_id, count(*) AS n FROM run_events "
        "WHERE type = 'protected_path_refused' GROUP BY run_id) AS counted "
        "WHERE runs.id = counted.run_id"
    )


def downgrade() -> None:
    op.drop_column("runs", "protected_attempts")
