"""Circuit breakers (13.7): `runs.breaker_trips`, how many times a breaker paused the run (one
per `breaker_tripped` event), kept as a summary column so the runs list never scans the event
log (backfilled from the events); and `runs.cost_baselines`, what each node usually costs, worked
out when the run is created and frozen on it.

Revision ID: 0043_circuit_breakers
Revises: 0042_review_dismissals
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_circuit_breakers"
down_revision: str | None = "0042_review_dismissals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("breaker_trips", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("runs", sa.Column("cost_baselines", postgresql.JSONB(), nullable=True))
    op.execute(
        "UPDATE runs SET breaker_trips = counted.n FROM ("
        "SELECT run_id, count(*) AS n FROM run_events "
        "WHERE type = 'breaker_tripped' GROUP BY run_id) AS counted "
        "WHERE runs.id = counted.run_id"
    )


def downgrade() -> None:
    op.drop_column("runs", "cost_baselines")
    op.drop_column("runs", "breaker_trips")
