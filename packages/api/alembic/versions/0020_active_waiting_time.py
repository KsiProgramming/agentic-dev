"""Active and waiting time: how long a run spent executing and paused at gates, projected from its
events like the other summary columns (`agentic_store.sink.time_values`).

Only live runs (queued, running, waiting) are filled from their `run_events`, so their wall-time
limit and their console stay right; runs that ended before keep `active_ms` null.

Revision ID: 0020_active_waiting_time
Revises: 0019_audit_events
Create Date: 2026-10-27
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0020_active_waiting_time"
down_revision: str | None = "0019_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("active_ms", "waiting_ms", "active_since", "waiting_since")

# Each live run's stretch boundaries in order, with the time of the event before each one.
BOUNDARIES = """
SELECT run_id, type, created_at, before FROM (
    SELECT e.run_id, e.seq, e.type, e.created_at,
        lag(e.created_at) OVER (PARTITION BY e.run_id ORDER BY e.seq) AS before
    FROM run_events e JOIN runs r ON r.id = e.run_id
    WHERE r.status IN ('queued', 'running', 'waiting')
) b
WHERE type IN ('run_started', 'run_resumed', 'gate_waiting')
ORDER BY run_id, seq
"""

UPDATE = """
UPDATE runs SET active_ms = :active_ms, waiting_ms = :waiting_ms,
    active_since = :active_since, waiting_since = :waiting_since
WHERE id = :id
"""


def _ms(start: datetime, end: datetime) -> int:
    return round((end - start).total_seconds() * 1000)


def _times(rows: list[Any]) -> dict[str, Any]:
    """The rules of `time_values`, replayed over one run's boundaries."""
    active: int | None = None
    waiting = 0
    active_since: datetime | None = None
    waiting_since: datetime | None = None
    for row in rows:
        if row.type == "gate_waiting":
            if active_since is not None:
                active = (active or 0) + _ms(active_since, row.created_at)
            active_since = None
            waiting_since = waiting_since or row.created_at
        else:
            active = active or 0
            if active_since is not None and row.before is not None:
                active += _ms(active_since, row.before)
            if waiting_since is not None:
                waiting += _ms(waiting_since, row.created_at)
            active_since, waiting_since = row.created_at, None
    return {
        "active_ms": active,
        "waiting_ms": waiting,
        "active_since": active_since,
        "waiting_since": waiting_since,
    }


def upgrade() -> None:
    op.add_column("runs", sa.Column("active_ms", sa.BigInteger(), nullable=True))
    op.add_column(
        "runs", sa.Column("waiting_ms", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.add_column("runs", sa.Column("active_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True))
    bind = op.get_bind()
    runs: dict[UUID, list[Any]] = {}
    for row in bind.execute(sa.text(BOUNDARIES)):
        runs.setdefault(row.run_id, []).append(row)
    for run_id, rows in runs.items():
        bind.execute(sa.text(UPDATE), {"id": run_id, **_times(rows)})


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("runs", column)
