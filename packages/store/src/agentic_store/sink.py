"""Persists a run's event stream to Postgres."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, null, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.events import (
    GATE_DECIDED,
    GATE_WAITING,
    NODE_FAILED,
    PR_OPENED,
    RUN_END_STATUS,
    RUN_FAILED,
    RUN_RESUMED,
    RUN_STARTED,
    RunEvent,
    RunStatus,
)
from agentic_store.models import Run, RunEventRow

RUN_EVENTS_CHANNEL = "run_events"
"""Postgres `NOTIFY` channel; the payload of each notification is `<run_id>:<seq>`."""

RUN_STATUS: dict[str, RunStatus] = {
    RUN_STARTED: "running",
    RUN_RESUMED: "running",
    GATE_WAITING: "waiting",
}
"""The run status each non-final event sets; the final ones are `RUN_END_STATUS`."""


def summary_values(event: RunEvent) -> dict[str, Any]:
    """The `runs` columns an event sets, beyond `updated_at`:

    | Event | Sets |
    |---|---|
    | `run_started` | `status=running`, `started_at` (the first start only) |
    | `run_resumed` | `status=running`, `waiting_gate=null` |
    | `gate_waiting` | `status=waiting`, `waiting_gate={node_id, title}` |
    | `gate_decided` | `waiting_gate=null` |
    | `pr_opened` | `pr_url` (the last one wins) |
    | `node_failed` with an `error` | `failure_reason="node <id>: <error>"` |
    | `run_completed`, `run_cancelled` | end status, `finished_at`; clears the gate and reason |
    | `run_failed` | `failed`, `finished_at`, clears `waiting_gate`; `failure_reason` = `error` |
    """
    values: dict[str, Any] = {}
    if status := RUN_STATUS.get(event.type) or RUN_END_STATUS.get(event.type):
        values["status"] = status
    payload = event.payload
    if event.type == RUN_STARTED:
        values["started_at"] = func.coalesce(Run.started_at, event.created_at)
    elif event.type in (RUN_RESUMED, GATE_DECIDED):
        values["waiting_gate"] = null()  # SQL NULL, not JSON null
    elif event.type == GATE_WAITING:
        title = payload.get("title")
        values["waiting_gate"] = {
            "node_id": event.node_id,
            "title": title if isinstance(title, str) else None,
        }
    elif event.type == PR_OPENED and isinstance(url := payload.get("url"), str):
        values["pr_url"] = url
    elif (
        event.type == NODE_FAILED
        and event.node_id is not None
        and isinstance(error := payload.get("error"), str)
    ):
        values["failure_reason"] = f"node {event.node_id}: {error}"
    if event.type in RUN_END_STATUS:
        values["finished_at"] = event.created_at
        values["waiting_gate"] = null()  # SQL NULL, not JSON null
        if event.type == RUN_FAILED:
            if isinstance(error := payload.get("error"), str):
                values["failure_reason"] = error
        else:
            values["failure_reason"] = None
    return values


class PostgresEventSink:
    """An `EventSink` that writes each event in its own transaction, so a live run is visible
    while it runs, and notifies `RUN_EVENTS_CHANNEL` when that transaction commits.

    The run's row must exist (see `create_run`). In the same transaction each event updates the
    run's summary columns (see `summary_values`): `run_started` and `run_resumed` set it to
    `running`, `gate_waiting` to `waiting`, and the final run event sets its end status."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def emit(self, event: RunEvent) -> None:
        async with self._sessions.begin() as session:
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
            if values := summary_values(event):
                await session.execute(
                    update(Run)
                    .where(Run.id == event.run_id)
                    .values(**values, updated_at=event.created_at)
                )
            # Delivered on commit, so a listener that wakes up can already read the row.
            await session.execute(
                select(func.pg_notify(RUN_EVENTS_CHANNEL, f"{event.run_id}:{event.seq}"))
            )


async def max_event_seq(sessions: async_sessionmaker[AsyncSession], run_id: UUID) -> int:
    """The `seq` of the run's last event, 0 if it has none; a resumed attempt carries on after."""
    async with sessions() as session:
        last = await session.scalar(
            select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
        )
    return last or 0


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
