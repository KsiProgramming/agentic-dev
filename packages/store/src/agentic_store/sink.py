"""Persists a run's event stream to Postgres."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import RUN_END_STATUS, RUN_STARTED, RunEvent
from agentic_store.models import Run, RunEventRow


class PostgresEventSink:
    """An `EventSink` that writes each event in its own transaction, so a live run is visible
    while it runs. `run_started` creates the `runs` row; the final run event sets its status."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def emit(self, event: RunEvent) -> None:
        async with self._sessions.begin() as session:
            if event.type == RUN_STARTED:
                session.add(
                    Run(
                        id=event.run_id,
                        status="running",
                        created_at=event.created_at,
                        updated_at=event.created_at,
                    )
                )
                await session.flush()
            session.add(
                RunEventRow(
                    run_id=event.run_id,
                    seq=event.seq,
                    type=event.type,
                    node_id=event.node_id,
                    payload=event.payload,
                    created_at=event.created_at,
                )
            )
            if status := RUN_END_STATUS.get(event.type):
                await session.execute(
                    update(Run)
                    .where(Run.id == event.run_id)
                    .values(status=status, updated_at=event.created_at)
                )


async def list_run_events(
    sessions: async_sessionmaker[AsyncSession], run_id: UUID, *, after_seq: int = 0
) -> list[RunEvent]:
    """A run's events with `seq > after_seq`, in order."""
    async with sessions() as session:
        rows = await session.scalars(
            select(RunEventRow)
            .where(RunEventRow.run_id == run_id, RunEventRow.seq > after_seq)
            .order_by(RunEventRow.seq)
        )
        return [
            RunEvent.model_validate(
                {
                    "run_id": row.run_id,
                    "seq": row.seq,
                    "type": row.type,
                    "node_id": row.node_id,
                    "payload": row.payload,
                    "created_at": row.created_at,
                }
            )
            for row in rows
        ]
